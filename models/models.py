# -*- coding: utf-8 -*-
import base64
import json
import requests

from odoo import models, fields, api
from .remote_model import RemoteModel

import logging

_logger = logging.getLogger(__name__)


def get_image_from_url(url):
    """
    :return: Returns a base64 encoded string.
    """
    data = ""
    try:
        data = base64.b64encode(requests.get(url.strip()).content).replace(b"\n", b"")
    except Exception as e:
        _logger.warning("Can’t load the image from URL %s" % url)
        logging.exception(e)
    return data


class Cinema(models.Model):
    _name = 'res.company'
    _inherit = 'res.company'
    _description = 'Кинотеатр'

    is_cinema = fields.Boolean('Кинотеатр')
    film_ids = fields.Many2many(comodel_name="films.film",
                                relation="films_cinema_film_rel",
                                column1="cinema_id", column2="film_id",
                                string="Список фильмов в кинотеатре")
    cinema_user_ids = fields.Many2many('res.users', 'films_cinema_user_rel',
                                       'cinema_id', 'user_id', string='Посетители кинотеатра')


class Film(models.Model):
    _name = 'films.film'
    _description = 'Фильм'

    name = fields.Char('Название фильма')
    poster_url = fields.Char('Постер')
    poster = fields.Binary(string="Постер", attachment=False)
    description = fields.Text('Описание')
    country_ru = fields.Char('Страна')
    year_start = fields.Char('Год')

    cinema_ids = fields.Many2many(comodel_name="res.company",
                                  relation="films_cinema_film_rel",
                                  column1="film_id", column2="cinema_id",
                                  string="Список кинотеатров, в которых есть фильм")
    show_film_ids = fields.One2many('films.show_film', 'film_id', string='Просмотры')
    remote_film_id = fields.Many2one('films.remote_film', string='Фильм из kinobd.net')

    @api.onchange('remote_film_id')
    def _onchange_remote_film_id(self):
        self.name = self.remote_film_id.name_russian
        if self.remote_film_id.small_poster:
            self.poster_url = self.remote_film_id.small_poster
            image = get_image_from_url(self.remote_film_id.small_poster)
            self.poster = image
            self.description = self.remote_film_id.description
            self.country_ru = self.remote_film_id.country_ru
            self.year_start = self.remote_film_id.year_start


class RemoteFilm(RemoteModel):
    _name = 'films.remote_film'
    _description = 'Модель для фильмов kinobd'
    _read_microservice = 'kinobd.listRead'
    _search_microservice = 'kinobd.listSearch'
    _rec_name = 'name_russian'

    name_russian = fields.Char("Название фильма")
    small_poster = fields.Char("Постер")
    description = fields.Text('Описание')
    country_ru = fields.Char('Страна')
    year_start = fields.Char('Год')

class ShowFilm(models.Model):
    _name = 'films.show_film'
    _description = 'Где, когда, какой фильм посмотрел человек'

    user_id = fields.Many2one('res.users', string='Кто посмотрел', default=lambda self: self.env.user)
    cinema_id = fields.Many2one('res.company', string='Где посмотрел')
    film_id = fields.Many2one('films.film', string='Какой фильм посмотрел')
    date = fields.Datetime(string='Когда посмотрел', default=lambda self: fields.datetime.now())

    @api.depends('film_id')
    def _compute_film_in_cinema_ids(self):
        for record in self:
            record.film_in_cinema_ids = [(6, 0, record.film_id.cinema_ids.ids)]
    film_in_cinema_ids = fields.Many2many('res.company', compute='_compute_film_in_cinema_ids')
