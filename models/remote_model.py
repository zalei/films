# -*- coding: utf-8 -*-
#  Native odoo microservice class
import json
import logging

from odoo.models import *
from odoo import models, fields, api
from odoo.osv.query import Query
from odoo.tools.translate import _
from odoo.exceptions import AccessError, MissingError

URL_KP_ID_URL = "https://kinobd.net/kp_id_list.txt"

with open("/opt/odoo15_snab/title.json", "r") as read_file:
    test_result_read = json.load(read_file)['data']

test_result_search = [film['id'] for film in test_result_read]

print(test_result_search)
print(test_result_read)


class RemoteModel(models.BaseModel):
    _auto = True
    _register = False
    _abstract = True
    _transient = False
    _remote = True
    _log_access = False

    _read_microservice = ""
    _search_microservice = ""

    @classmethod
    def is_remote(cls):
        return cls._remote

    def _call_rpc(self, rpc_class, rpc_method, *args, **kwargs):
        try:
            if rpc_class == 'kinobd':
                if rpc_method == 'listSearch':
                    result = test_result_search
                elif rpc_method == 'listRead':
                    result = test_result_read
            else:
                result = []
        except Exception as exc:
            logging.error(f"===== RUN RPC ERROR:{rpc_class}.{rpc_method} - {str(exc)}")
            raise MissingError(f"Ошибка: {rpc_class}.{rpc_method} - {str(exc)}")
        return result

    # def _call_rpc(self, rpc_class, rpc_method, *args, **kwargs):
    #     try:
    #         rpc = NamekoProxy(timeout=NAMEKO_TIMEOUT)
    #         result = getattr(rpc[rpc_class], rpc_method)(*args)
    #     except Exception as exc:
    #         logging.error(f"===== RUN RPC ERROR:{rpc_class}.{rpc_method} - {str(exc)}")
    #         raise MissingError(f"Сетевая ошибка: Не удалось связаться с серверами УП Витебскоблгаз. Детали: {rpc_class}.{rpc_method} - {str(exc)}")
    #     return result

    @api.model
    def _search(self, args, offset=0, limit=None, order=None, count=False, access_rights_uid=None, **kwargs):
        """
        Переопределение приватного метода поиска BaseModel.
        для получение id записей из вызова микросервисов Nameko
        """
        (rpc_class, rpc_search_method) = self._search_microservice.split(".")
        if not rpc_class or not rpc_search_method:
            raise MissingError(_("У вашей модели нет свойства _search_microservice"))

        model = self.with_user(access_rights_uid) if access_rights_uid else self
        model.check_access_rights("read")
        self._flush_search(args, order=order)
        query = self._where_calc(args)
        self._apply_ir_rules(query, "read")

        # if expression.is_false(self, args):
        #     return 0 if count else []

        if count:
            query = self._call_rpc(rpc_class, rpc_search_method, True, None, None, args, **kwargs)
            return query if isinstance(query, int) else len(query)

        query = self._call_rpc(rpc_class, rpc_search_method, False, limit, offset, args, **kwargs)
        return query

    def _read(self, fields, **kwargs):
        """
        Переопределение приватного чтения полей BaseModel.
        для получение дынных по id записей из вызова микросервисов Nameko
        """
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
