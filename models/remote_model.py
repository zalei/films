# -*- coding: utf-8 -*-
#  Native odoo microservice class
import json
import logging

import requests

from odoo.models import *
from odoo import models, fields, api
from odoo.osv.query import Query
from odoo.tools.translate import _
from odoo.exceptions import AccessError, MissingError

headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36'}

URL_KP_ID_LIST = "https://kinobd.net/kp_id_list.txt"  # Список ID (Kinopoisk ID) фильмов, плееры для которых есть в БД

class RemoteModel(models.BaseModel):
    _auto = True
    _register = False
    _abstract = True
    _transient = False
    _remote = True
    _log_access = False
    _remote_film_kp_id_list = []

    def update_remote_film_kp_id_list(self):
        response = requests.get(URL_KP_ID_LIST)
        print(response.text)
        self._remote_film_kp_id_list = list(response.text)

    _read_microservice = ""
    _search_microservice = ""

    @classmethod
    def is_remote(cls):
        return cls._remote


    def _call_rpc(self, rpc_class, rpc_method, *args, **kwargs):
        try:
            print(f'********** _call_rpc: [{rpc_method.upper()}]: {args} {kwargs} **********')
            if rpc_class == 'kinobd':
                if rpc_method == 'listSearch':
                    if len(args[3]):
                        name_russian_search = args[3][0][2]  # слово поиска
                        response = requests.get(f"https://kinobd.net/api/films/search/title?q={name_russian_search}",
                                                headers=headers)
                        result_search_json = json.loads(response.text)['data']
                        result = [film['id'] for film in result_search_json[0:3]]
                    else:
                        response = requests.get("https://kinobd.ru/api/films", headers=headers)
                        result_search_json = json.loads(response.text)['data']
                        result = [film['id'] for film in result_search_json[0:3]]

                elif rpc_method == 'listRead':
                    read_film_ids = list(args[0])
                    read_film_data = []
                    # Найдем, какие страницы нужно считать с api, т.к. к api не нашел документации и поиска по id:
                    set_of_pages = set([])
                    for film_id in read_film_ids:
                        # страница page в ссылке "https://kinobd.ru/api/films?page=...", на которой находится film_id
                        page_of_film_id = (film_id - 1) // 50 + 1
                        set_of_pages |= set([page_of_film_id])

                    print(f'*** film_ids: {read_film_ids} найдены на {set_of_pages} страницах')
                    for page in set_of_pages:
                        response = requests.get(f"https://kinobd.ru/api/films?page={page}", headers=headers)
                        film_ids = json.loads(response.text)['data']
                        for film_id in film_ids:
                            if film_id['id'] in read_film_ids:
                                read_film_data.append(film_id)
                    result = read_film_data  # list of dict
            else:
                result = []
        except Exception as exc:
            logging.error(f"===== RUN RPC ERROR:{rpc_class}.{rpc_method} - {str(exc)}")
            raise MissingError(f"Ошибка: {rpc_class}.{rpc_method} - {str(exc)}")
        print('len(result) of [_call_rpc]', len(result))
        return result


    @api.model
    def _search(self, args, offset=0, limit=None, order=None, count=False, access_rights_uid=None):
        """
        Private implementation of search() method, allowing specifying the uid to use for the access right check.
        This is useful for example when filling in the selection list for a drop-down and avoiding access rights errors,
        by specifying ``access_rights_uid=1`` to bypass access rights check, but not ir.rules!
        This is ok at the security level because this method is private and not callable through XML-RPC.

        :param access_rights_uid: optional user ID to use when checking access rights
                                  (not for ir.rules, this is only for ir.model.access)
        :return: a list of record ids or an integer (if count is True)
        """
        (rpc_class, rpc_search_method) = self._search_microservice.split(".")
        if not rpc_class or not rpc_search_method:
            raise MissingError(_("У модели нет свойства _search_microservice"))

        # the flush must be done before the _where_calc(), as the latter can do some selects
        self._flush_search(args, order=order)

        query = self._call_rpc(rpc_class, rpc_search_method, True, None, None, args)  # list of record ids
        # print('_search query?', query)
        # return query if isinstance(query, int) else query

        # возвращает запрос к БД в случае локальной модели и строку для поиска в случае kinobd
        print('***[_search]*** return list of record ids:', query)
        return query

    def _read(self, fields, **kwargs):
        """
        Переопределение приватного чтения полей BaseModel.
        для получение дынных по id записей из вызова микросервисов Nameko
        """
        # print(fields)
        # print(kwargs)
        if not self:
            return
        self.check_access_rights("read")
        self.flush(fields, self)

        field_names = []
        inherited_field_names = []
        for name in fields:
            field = self._fields.get(name)
            if field:
                if field.store:
                    field_names.append(name)
                elif field.base_field.store:
                    inherited_field_names.append(name)
            else:
                logging.warning("%s.read() with unknown field '%s'", self._name, name)

        # determine the fields that are stored as columns in tables; ignore 'id'
        fields_pre = [
            field for field in (self._fields[name] for name in field_names + inherited_field_names) if field.name != "id" if field.base_field.store and field.base_field.column_type if not (field.inherited and callable(field.base_field.translate))
        ]

        if fields_pre:
            env = self.env
            cr, user, context, su = env.args

            # make a query object for selecting ids, and apply security rules to it
            query = Query(self.env.cr, self._table, self._table_query)
            self._apply_ir_rules(query, "read")

            # the query may involve several tables: we need fully-qualified names
            def qualify(field):
                col = field.name
                res = self._inherits_join_calc(self._table, field.name, query)
                if field.type == "binary" and (context.get("bin_size") or context.get("bin_size_" + col)):
                    # PG 9.2 introduces conflicting pg_size_pretty(numeric) -> need ::cast
                    res = "pg_size_pretty(length(%s)::bigint)" % res
                return '%s as "%s"' % (res, col)

            # selected fields are: 'id' followed by fields_pre
            qual_names = [qualify(name) for name in [self._fields["id"]] + fields_pre]

            # determine the actual query to execute (last parameter is added below)
            query.add_where('"%s".id IN %%s' % self._table)
            query_str, params = query.select(*qual_names)

            result = []
            for sub_ids in cr.split_for_in_conditions(self.ids):
                (rpc_class, rpc_read_method) = self._read_microservice.split(".")
                if not rpc_class or not rpc_read_method:
                    raise MissingError(_("У вашей модели нет свойства _read_microservice"))
                results = self._call_rpc(rpc_class, rpc_read_method, sub_ids)
                result = []
                for res in results:
                    mas_r = [res["id"]]
                    for fie_ in fields:
                        if fie_ in res and fie_ != "id":
                            mas_r.append(res[fie_])
                    result.append(tuple(mas_r))

        else:
            self.check_access_rule("read")
            result = [(id_,) for id_ in self.ids]

        fetched = self.browse()
        if result:
            cols = zip(*result)
            ids = next(cols)
            fetched = self.browse(ids)

            for field in fields_pre:
                values = next(cols)
                if context.get("lang") and not field.inherited and callable(field.translate):
                    translate = field.get_trans_func(fetched)
                    values = list(values)
                    for index in range(len(ids)):
                        values[index] = translate(ids[index], values[index])

                # store values in cache
                self.env.cache.update(fetched, field, values)

            # determine the fields that must be processed now;
            # for the sake of simplicity, we ignore inherited fields
            for name in field_names:
                field = self._fields[name]
                if not field.column_type:
                    field.read(fetched)

        # possibly raise exception for the records that could not be read
        missing = self - fetched
        if missing:
            extras = fetched - self
            if extras:
                raise AccessError(
                    _("Database fetch misses ids ({}) and has extra ids ({}), may be caused by a type incoherence in a previous request").format(
                        missing._ids,
                        extras._ids,
                    )
                )
            # mark non-existing records in missing
            forbidden = missing.exists()
            if forbidden:
                raise self.env["ir.rule"]._make_access_error("read", forbidden)
