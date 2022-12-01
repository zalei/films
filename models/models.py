# -*- coding: utf-8 -*-
from odoo import models, fields, api
# from odoo.addons.oblgas_base import RemoteModel

import logging
_logger = logging.getLogger(__name__)


class Cinema(models.Model):
    _name = 'films.cinema'
    _inherit = 'res.company'
    _description = 'Кинотеатр'

    film_ids = fields.Many2many(comodel_name="films.film",
                                relation="films_cinema_film_rel",
                                column1="cinema_id", column2="film_id",
                                string="Список фильмов в кинотеатре")
    user_ids = fields.Many2many('res.users', 'films_cinema_user_rel',
                                'cinema_id', 'user_id', string='Посетители кинотеатра')


class Film(models.Model):
    _name = 'films.film'
    _description = 'Фильм'

    name = fields.Char('Название фильма')
    poster = fields.Binary('Постер', attachment=False)

    cinema_ids = fields.Many2many(comodel_name="films.cinema",
                                  relation="films_cinema_film_rel",
                                  column1="film_id", column2="cinema_id",
                                  string="Список кинотеатров, в которых есть фильм")
    show_film_ids = fields.One2many('films.show_film', 'film_id', string='Просмотры')

    @api.model
    def _search(self, args, offset=0, limit=None, order=None, count=False, access_rights_uid=None):
        model = self.with_user(access_rights_uid) if access_rights_uid else self
        model.check_access_rights('read')

        if expression.is_false(self, args):
            # optimization: no need to query, as no record satisfies the domain
            return 0 if count else []

        # the flush must be done before the _where_calc(), as the latter can do some selects
        self._flush_search(args, order=order)

        query = self._where_calc(args)
        self._apply_ir_rules(query, 'read')

        if count:
            # Ignore order, limit and offset when just counting, they don't make sense and could
            # hurt performance
            query_str, params = query.select("count(1)")
            self._cr.execute(query_str, params)
            res = self._cr.fetchone()
            return res[0]

        query.order = self._generate_order_by(order, query).replace('ORDER BY ', '')
        query.limit = limit
        query.offset = offset

        return query

    def _read(self, fields):
        if not self:
            return
        self.check_access_rights('read')

        # if a read() follows a write(), we must flush updates, as read() will
        # fetch from database and overwrites the cache (`test_update_with_id`)
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
                _logger.warning("%s.read() with unknown field '%s'", self._name, name)

        # determine the fields that are stored as columns in tables; ignore 'id'
        fields_pre = [
            field
            for field in (self._fields[name] for name in field_names + inherited_field_names)
            if field.name != 'id'
            if field.base_field.store and field.base_field.column_type
            if not (field.inherited and callable(field.base_field.translate))
        ]

        if fields_pre:
            env = self.env
            cr, user, context, su = env.args

            # make a query object for selecting ids, and apply security rules to it
            query = Query(self.env.cr, self._table, self._table_query)
            self._apply_ir_rules(query, 'read')

            # the query may involve several tables: we need fully-qualified names
            def qualify(field):
                col = field.name
                res = self._inherits_join_calc(self._table, field.name, query)
                if field.type == 'binary' and (context.get('bin_size') or context.get('bin_size_' + col)):
                    # PG 9.2 introduces conflicting pg_size_pretty(numeric) -> need ::cast
                    res = 'pg_size_pretty(length(%s)::bigint)' % res
                return '%s as "%s"' % (res, col)

            # selected fields are: 'id' followed by fields_pre
            qual_names = [qualify(name) for name in [self._fields['id']] + fields_pre]

            # determine the actual query to execute (last parameter is added below)
            query.add_where('"%s".id IN %%s' % self._table)
            query_str, params = query.select(*qual_names)

            result = []
            for sub_ids in cr.split_for_in_conditions(self.ids):
                cr.execute(query_str, params + [sub_ids])
                result += cr.fetchall()
        else:
            self.check_access_rule('read')
            result = [(id_,) for id_ in self.ids]

        fetched = self.browse()
        if result:
            cols = zip(*result)
            ids = next(cols)
            fetched = self.browse(ids)

            for field in fields_pre:
                values = next(cols)
                if context.get('lang') and not field.inherited and callable(field.translate):
                    values = list(values)
                    if any(values):
                        translate = field.get_trans_func(fetched)
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
                if field.deprecated:
                    _logger.warning('Field %s is deprecated: %s', field, field.deprecated)

        # possibly raise exception for the records that could not be read
        missing = self - fetched
        if missing:
            extras = fetched - self
            if extras:
                raise AccessError(
                    _("Database fetch misses ids ({}) and has extra ids ({}), may be caused by a type incoherence in a previous request").format(
                        missing._ids, extras._ids,
                    ))
            # mark non-existing records in missing
            forbidden = missing.exists()
            if forbidden:
                raise self.env['ir.rule']._make_access_error('read', forbidden)




class ShowFilm(models.Model):
    _name = 'films.show_film'
    _description = 'Где, когда, какой фильм посмотрел человек'

    user_id = fields.Many2one('res.users', string='Кто посмотрел')
    cinema_id = fields.Many2one('films.cinema', string='Где посмотрел')
    film_id = fields.Many2one('films.film', string='Какой фильм посмотрел')
    date = fields.Datetime(string='Когда посмотрел', default=lambda: fields.datetime.now())
