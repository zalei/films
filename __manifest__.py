# -*- coding: utf-8 -*-
{
    'name': "films",
    'sequence': 1,
    'author': "Zaleusky Yauheny",
    'category': 'Marketing',
    'version': '0.1',

    'summary': """ Модуль кинотеатра и просмотренных фильмов""",
    'description': """
        приложение при помощи которого можно найти фильм во внешнем API и сохранить его в БД,
        добавить кинотеатры, и делать записи о человеке, когда, где и какой фильм он посмотрел 
    """,

    'depends': ['base'],

    'data': [
        'security/ir.model.access.csv',
        'views/views.xml',
    ],

    'installable': True,
    'application': True,
    'auto_install': False,

    'license': 'LGPL-3'
}
