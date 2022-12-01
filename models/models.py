# -*- coding: utf-8 -*-
import json
import requests

from odoo import models, fields, api
from .remote_model import RemoteModel

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

    @api.depends('remote_film_id')
    def _compute_name(self):
        for record in self:
            record.name = record.remote_film_id.name_russian
    name = fields.Char('Название фильма', compute='_compute_name', store=True)
    poster_url = fields.Char('Постер', attachment=False)

    def get_image_from_url(self, url):
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

    @api.depends("poster_url")
    def _compute_poster(self):
        for record in self:
            image = None
            if record.poster_url:
                image = self.get_image_from_url(record.poster_url)
                # self.check_access_rule()
            record.update({"poster": image, })
    poster = fields.Binary(string="Image", compute="_compute_poster", store=True, attachment=False)

    cinema_ids = fields.Many2many(comodel_name="films.cinema",
                                  relation="films_cinema_film_rel",
                                  column1="film_id", column2="cinema_id",
                                  string="Список кинотеатров, в которых есть фильм")
    show_film_ids = fields.One2many('films.show_film', 'film_id', string='Просмотры')
    remote_film_id = fields.Many2one('films.remote_film', string='Фильм из kinobd.net')

    @api.onchange('remote_film_id')
    def _onchange_remote_film_id(self):
        self.name = self.remote_film_id.name_russian
        self.poster_url = self.remote_film_id.small_poster

class RemoteFilm(RemoteModel):
    _name = 'films.remote_film'
    _read_microservice = 'kinobd.listRead'
    _search_microservice = 'kinobd.listSearch'
    _rec_name = 'name_russian'

    name_russian = fields.Char("Название фильма")
    small_poster = fields.Char("Постер")


class ShowFilm(models.Model):
    _name = 'films.show_film'
    _description = 'Где, когда, какой фильм посмотрел человек'

    user_id = fields.Many2one('res.users', string='Кто посмотрел')
    cinema_id = fields.Many2one('films.cinema', string='Где посмотрел')
    film_id = fields.Many2one('films.film', string='Какой фильм посмотрел')
    date = fields.Datetime(string='Когда посмотрел', default=lambda: fields.datetime.now())


