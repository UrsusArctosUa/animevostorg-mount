#!/usr/bin/env python3

'''
Created on Oct 30, 2018

@author: Dmytro Dubrovny <dubrovnyd@gmail.com>
'''

from typing import List, Iterator
from cachetools import cached, TTLCache
from webfs import File, Directory, Playlist, PlaylistItem, FSItem, FuseOSError
import json
import os
import requests
import toml
import errno


class GetTokenError(Exception):

    def __init__(self, message: str = ''):
        self.__message = message

    def __str__(self) -> str:
        return self.__message


class Configuration:
    def __init__(self, path: str, quality: str):
        self.__api_url = None
        self.__path = path
        self.__quality = quality
        if os.path.isfile(path):
            configuration = toml.load(path)
            configuration.setdefault('username', None)
            configuration.setdefault('password', None)
            self.__username = configuration['username']
            self.__password = configuration['password']
        self.__limit = 40

    @property
    def limit(self) -> int:
        return self.__limit

    @property
    def quality(self):
        return self.__quality

    @property
    def api_url(self) -> str:
        if self.__api_url is not None:
            return self.__api_url
        # self.__api_url = 'https://api.animevost.org/v1'
        self.__api_url = 'https://api.animetop.info/v1'
        return self.__api_url

    @property
    @cached(cache=TTLCache(maxsize=128, ttl=30000))
    def token(self):
        if self.__username is None or self.__password is None:
            raise GetTokenError("Username or password is not configured")
        page = requests.post('{:s}/gettoken'.format(self.api_url), {'user': self.__username, 'pass': self.__password})
        data = json.loads(page.text)
        if data['status'] == 'ok':
            return data['token']
        raise GetTokenError(data['error'])

    @staticmethod
    def qualities() -> List[str]:
        return ['std', 'hd']


class TitleFinder:
    FIELD_GENRE = 'gen'
    FIELD_NAME = 'name'
    FIELD_CATEGORY = 'cat'
    FIELD_YEAR = 'year'

    def __init__(self, config: Configuration, **params):
        self.__config = config
        self.__params = params

    def __iter__(self) -> Iterator[FSItem]:
        return iter(self.__search())

    @cached(cache=TTLCache(maxsize=1024, ttl=3000))
    def __search(self) -> List[FSItem]:
        page = requests.post('{:s}/search'.format(self.__config.api_url), self.__params)
        series = json.loads(page.text)
        series.setdefault('data', [])
        titles = [Title('{:02d} {:s}'.format(i, s['title']), s['id'], self.__config) for i, s in
                  enumerate(series['data'], start=1)]
        return titles


class Episode(PlaylistItem):

    def __init__(self, title: str, urls: dict, config: Configuration):
        PlaylistItem.__init__(self, title, '')
        self.__urls = urls
        self.__config = config

    def __lt__(self, other: 'Episode') -> bool:
        self_split = self.title.split(' ')[0]
        other_split = other.title.split(' ')[0]
        try:
            self_num = int(self_split)
        except ValueError:
            try:
                int(other_split)
            except ValueError:
                return self.title < other.title
            return False
        try:
            other_num = int(other_split)
        except ValueError:
            return True
        return int(self_num) < int(other_num)

    @property
    @cached(cache=TTLCache(maxsize=1024, ttl=3000))
    def path(self) -> str:
        if self.__config.quality in self.__urls and requests.head(self.__urls[self.__config.quality]).ok:
            return self.__urls[self.__config.quality]
        else:
            for quality in Configuration.qualities():
                if quality in self.__urls and requests.head(self.__urls[quality]).ok:
                    return self.__urls[quality]
        return ''


class Title(Directory):

    def __init__(self, name: str, title_id: int, config: Configuration):
        Directory.__init__(self, name)
        self.__title_id = title_id
        self.__config = config

    def __iter__(self):
        return iter(self.__items())

    @cached(cache=TTLCache(maxsize=1024, ttl=3000))
    def __items(self) -> List[FSItem]:
        page = requests.post('{:s}/playlist'.format(self.__config.api_url), {'id': self.__title_id}, None)
        series_data = json.loads(page.text)
        series = []
        for episode_data in series_data:
            series.append(Episode(episode_data['name'], episode_data, self.__config))
        sorted_series = sorted(series)
        total = len(sorted_series)
        if total < self.__config.limit * 1.2:
            items = self.__create_playlists(sorted_series)
        else:
            items = []
            for i in range(0, total, self.__config.limit):
                chunk = sorted_series[i:i + self.__config.limit]
                items.append(
                    Directory('{:03d}-{:03d}'.format(i + 1, min(i + self.__config.limit, total)),
                              self.__create_playlists(chunk)))
        return items

    @staticmethod
    def __create_playlists(items: Iterator[PlaylistItem]) -> Iterator[Playlist]:
        return [Playlist(item.title, items[n:]) for n, item in enumerate(items)]


class Page(Directory):

    def __init__(self, name: str, number: int, config: Configuration, limit: int = 99):
        Directory.__init__(self, name)
        self.__number = number
        self.__config = config
        self.__limit = limit

    def __iter__(self) -> Iterator[FSItem]:
        return iter(self.__titles())

    @cached(cache=TTLCache(maxsize=1024, ttl=3000))
    def __titles(self) -> List[FSItem]:
        page = requests.get(
            '{:s}/last?page={:d}&quantity={:d}'.format(self.__config.api_url, self.__number, self.__limit))
        series = json.loads(page.text)
        titles = [Title('{:02d} {:s}'.format(i, s['title']), s['id'], self.__config) for i, s in
                  enumerate(series['data'], start=1)]
        return titles


class Search(Directory):

    def __init__(self, name: str, field: str, config: Configuration):
        Directory.__init__(self, name)
        self.__history = dict()
        self.__field = field
        self.__config = config

    def __iter__(self) -> Iterator[FSItem]:
        return iter(self.__history.values())

    def find(self, path: str) -> 'FSItem':
        if path == '':
            return self

        path_listed = path.split(os.sep)
        search_query = path_listed.pop(0)
        if search_query not in self.__history:
            search_title = TitleFinder(self.__config, **{self.__field: search_query})
            self.__history[search_query] = Directory(search_query, search_title)
        deeper_path = os.sep.join(path_listed)
        return self.__history[search_query].find(deeper_path)


class Genres(Directory):

    def __init__(self, name: str, config: Configuration):
        Directory.__init__(self, name)
        self.__items = dict()
        self.__config = config

    def __iter__(self) -> Iterator[FSItem]:
        return iter(self.__genres())

    @cached(cache=TTLCache(maxsize=1024, ttl=3000))
    def __genres(self):
        page = requests.get('{:s}/genres'.format(self.__config.api_url))
        data = json.loads(page.text)
        return [genre for genre in data.values()]

    def find(self, path: str) -> 'FSItem':
        if path == '':
            return self

        path_listed = path.split(os.sep)
        genre = path_listed.pop(0)
        if genre not in self.__genres():
            raise FuseOSError(errno.ENOENT)

        if genre not in self.__items:
            self.__items[genre] = Directory(genre, TitleFinder(self.__config, **{TitleFinder.FIELD_GENRE: genre}))
        deeper_path = os.sep.join(path_listed)
        return self.__items[genre].find(deeper_path)


class Favorites(Directory):

    def __init__(self, name: str, config: Configuration):
        Directory.__init__(self, name)
        self.__config = config

    def __iter__(self) -> Iterator[FSItem]:
        return iter(self.__titles())

    @cached(cache=TTLCache(maxsize=1024, ttl=3000))
    def __titles(self) -> List[FSItem]:
        try:
            token = self.__config.token
        except GetTokenError as err:
            return [File('error.txt', str(err))]
        else:
            page = requests.post('{:s}/favorites'.format(self.__config.api_url), {'token': token})
            series = json.loads(page.text)
            titles = [Title('{:02d} {:s}'.format(i, s['title']), s['id'], self.__config) for i, s in
                      enumerate(series['data'], start=1)]
            return titles


class All(Directory):

    def __init__(self, name: str, config: Configuration, limit: int = 99):
        Directory.__init__(self, name)
        self.__config = config
        self.__limit = limit

    def __iter__(self) -> Iterator[FSItem]:
        return iter(self.__pages())

    @cached(cache=TTLCache(maxsize=1024, ttl=3000))
    def __pages(self) -> List[FSItem]:
        page = requests.get('{:s}/last?page=1&quantity={:d}'.format(self.__config.api_url, self.__limit))
        series = json.loads(page.text)
        if len(series['data']) < self.__limit:
            self.__limit = len(series['data'])
        last_page = series['state']['count'] // self.__limit + 1
        pages = [Page('{:03d}'.format(page), page, self.__config, self.__limit) for page in range(1, last_page + 1)]
        return pages


class Root(Directory):

    def __init__(self, config: Configuration):
        directories = [
            Page('latest', 1, config),
            All('all', config),
            Genres('genres', config),
            Directory('search', [
                Search('by-name', TitleFinder.FIELD_NAME, config),
                Search('by-category', TitleFinder.FIELD_CATEGORY, config),
                Search('by-year', TitleFinder.FIELD_YEAR, config)
            ]),
            Favorites('favorites', config)
        ]
        Directory.__init__(self, '', directories)


if __name__ == '__main__':
    from webfs import mount, parse_options, argument_parser

    parser = argument_parser()
    parser.add_argument('quality', type=str, help='Video quality', choices=Configuration.qualities())
    parser.add_argument('path', type=str, help='Target path')
    parser.add_argument('-c', '--configuration', type=str, help='Path to config file', default='')

    arguments = parser.parse_args()
    options = parse_options(arguments)
    options.setdefault('fsname', 'doc.org-{:s}-fuse'.format(arguments.quality))
    options.setdefault('conf', arguments.configuration)
    conf = Configuration(options['conf'], arguments.quality)
    del options['conf']

    mount(Root(conf), arguments.path, **options)
