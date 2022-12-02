# -*- coding: utf-8 -*-
# Monekey patch models and Fields

from odoo import models, fields
from odoo.fields import *


def update_db_foreign_key(self, model, column):
    """
    Удаление 'Foreign Key' для полей которые ссылаюься на микросервисные модели
    Для m2o
    """
    comodel = model.env[self.comodel_name]
    # foreign keys do not work on views, and users can define custom models on sql views.
    if comodel.is_remote() or model.is_remote():
        return
    if not model._is_an_ordinary_table() or not comodel._is_an_ordinary_table():
        return
    # ir_actions is inherited, so foreign key doesn't work on it
    if not comodel._auto or comodel._table == "ir_actions":
        return
    # create/update the foreign key, and reflect it in 'ir.model.constraint'
    model.pool.add_foreign_key(model._table, self.name, comodel._table, "id", self.ondelete or "set null", model, self._module)


def update_db_foreign_keys(self, model):
    """
    Удаление 'Foreign Key' для полей которые ссылаются на микросервисные модели
    Для m2m
    """
    comodel = model.env[self.comodel_name]
    if not model.is_remote():
        if model._is_an_ordinary_table():
            model.pool.add_foreign_key(
                self.relation,
                self.column1,
                model._table,
                "id",
                "cascade",
                model,
                self._module,
                force=False,
            )
        if comodel._is_an_ordinary_table():
            model.pool.add_foreign_key(
                self.relation,
                self.column2,
                comodel._table,
                "id",
                self.ondelete,
                model,
                self._module,
            )


def read(self, records):
    """
    в случае если ссылается на микросервисную модель
    """
    context = {"active_test": False}
    context.update(self.context)
    comodel = records.env[self.comodel_name].with_context(**context)
    domain = self.get_domain_list(records)
    comodel._flush_search(domain)
    wquery = comodel._where_calc(domain)
    comodel._apply_ir_rules(wquery, "read")
    order_by = comodel._generate_order_by(None, wquery)
    from_c, where_c, where_params = wquery.get_sql()
    if not comodel.is_remote():
        query = """ SELECT {rel}.{id1}, {rel}.{id2} FROM {rel}, {from_c}
                    WHERE {where_c} AND {rel}.{id1} IN %s AND {rel}.{id2} = {tbl}.id
                    {order_by}
                """.format(
            rel=self.relation, id1=self.column1, id2=self.column2, tbl=comodel._table, from_c=from_c, where_c=where_c or "1=1", order_by=order_by
        )
    else:
        query = """ SELECT {rel}.{id1}, {rel}.{id2} FROM {rel}
                    WHERE {where_c} AND {rel}.{id1} IN %s
                    {limit} OFFSET {offset}
                """.format(
            rel=self.relation, id1=self.column1, id2=self.column2, where_c=where_c or "1=1", limit=(" LIMIT %d" % self.limit) if self.limit else "", offset=0
        )
    where_params.append(tuple(records.ids))

    # retrieve lines and group them by record
    group = defaultdict(list)
    records._cr.execute(query, where_params)
    for row in records._cr.fetchall():
        group[row[0]].append(row[1])

    # store result in cache
    cache = records.env.cache
    for record in records:
        cache.set(record, self, tuple(group[record.id]))


@classmethod
def is_remote(cls):
    return cls._remote


# Monkey Patch для odoo.models
models.PREFETCH_MAX = 160000
models.BaseModel._remote = False
models.Model._remote = False
models.TransientModel._remote = False
models.BaseModel.is_remote = is_remote

# Monkey Patch для odoo.models.MetaModel
def __init__(self, name, bases, attrs):
    # super().__init__(name, bases, attrs)

    if not attrs.get("_register", True):
        return

    # Remember which models to instantiate for this module.
    if self._module:
        self.module_to_models[self._module].append(self)

    if not self._abstract and self._name not in self._inherit:
        # this class defines a model: add magic fields
        def add(name, field):
            setattr(self, name, field)
            field.__set_name__(self, name)

        def add_default(name, field):
            if name not in attrs:
                setattr(self, name, field)
                field.__set_name__(self, name)

        add("id", fields.Id(automatic=True))
        add(self.CONCURRENCY_CHECK_FIELD, fields.Datetime(string="Last Modified on", automatic=True, compute="_compute_concurrency_field", compute_sudo=False))
        add_default("display_name", fields.Char(string="Display Name", automatic=True, compute="_compute_display_name"))

        if attrs.get("_log_access", self._auto):
            add_default("create_uid", fields.Many2one("res.users", string="Created by", automatic=True, readonly=True))
            add_default("create_date", fields.Datetime(string="Created on", automatic=True, readonly=True))
            add_default("write_uid", fields.Many2one("res.users", string="Last Updated by", automatic=True, readonly=True))
            add_default("write_date", fields.Datetime(string="Last Updated on", automatic=True, readonly=True))

    elif self.is_remote:
        # this class defines a model: add magic fields
        def add(name, field):
            setattr(self, name, field)
            field.__set_name__(self, name)

        def add_default(name, field):
            if name not in attrs:
                setattr(self, name, field)
                field.__set_name__(self, name)

        add("id", fields.Id(automatic=True))
        add(self.CONCURRENCY_CHECK_FIELD, fields.Datetime(string="Last Modified on", automatic=True, compute="_compute_concurrency_field", compute_sudo=False))
        add_default("display_name", fields.Char(string="Display Name", automatic=True, compute="_compute_display_name"))


models.MetaModel.__init__ = __init__

# Monkey Patch для odoo.fields
fields.Many2one.update_db_foreign_key = update_db_foreign_key
fields.Many2many.update_db_foreign_keys = update_db_foreign_keys
fields.Many2many.read = read