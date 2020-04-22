#!/usr/bin/env python3

'''
Created on Oct 30, 2018

@author: Dmytro Dubrovny <dubrovnyd@gmail.com>
'''

from typing import List, Iterator
from cachetools import cached, TTLCache
from webfs import File, Directory, Playlist, PlaylistItem, FileOrDirectory, FuseOSError
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
        self.__limit = 99

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
        page = requests.post("%s/gettoken" % self.api_url, {'user': self.__username, 'pass': self.__password})
        data = json.loads(page.text)
        if data['status'] == 'ok':
            return data['token']
        raise GetTokenError(data['error'])

    @staticmethod
    def qualities() -> List[str]:
        return ['std', 'hd']


class SearchTitle:
    FIELD_GENRE = 'gen'
    FIELD_NAME = 'name'
    FIELD_CATEGORY = 'cat'
    FIELD_YEAR = 'year'

    def __init__(self, field: str, value: str, config: Configuration):
        self.__field = field
        self.__value = value
        self.__config = config

    def __iter__(self) -> Iterator[FileOrDirectory]:
        return iter(self.__search())

    @cached(cache=TTLCache(maxsize=1024, ttl=3000))
    def __search(self) -> List[FileOrDirectory]:
        page = requests.post("%s/search" % self.__config.api_url, {self.__field: self.__value})
        series = json.loads(page.text)
        series.setdefault('data', [])
        titles = [TitleDirectory("%02d %s" % (i, s['title']), s['id'], self.__config) for i, s in
                  enumerate(series['data'], start=1)]
        return titles


class Episode(PlaylistItem):

    def __init__(self, title, url):
        PlaylistItem.__init__(self, title, url)

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


class TitleDirectory(Directory):

    def __init__(self, name: str, title_id: int, config: Configuration):
        Directory.__init__(self, name)
        self.__title_id = title_id
        self.__config = config

    def __iter__(self):
        return iter(self.__playlist())

    @cached(cache=TTLCache(maxsize=1024, ttl=3000))
    def __playlist(self) -> List[Playlist]:
        page = requests.post("%s/playlist" % self.__config.api_url, {'id': self.__title_id}, None)
        series_data = json.loads(page.text)
        series = []
        for episode_data in series_data:
            if self.__config.quality in episode_data and requests.head(episode_data[self.__config.quality]).ok:
                series.append(Episode(episode_data['name'], episode_data[self.__config.quality]))
            else:
                for quality in Configuration.qualities():
                    if quality in episode_data and requests.head(episode_data[quality]).ok:
                        series.append(Episode(episode_data['name'], episode_data[quality]))
                        break
                pass
        sorted_series = sorted(series)
        playlists = [Playlist(episode.title, sorted_series[i:]) for i, episode in enumerate(sorted_series)]
        return playlists


class Page(Directory):

    def __init__(self, name: str, number: int, config: Configuration, limit: int=99):
        Directory.__init__(self, name)
        self.__number = number
        self.__config = config
        self.__limit = limit

    def __iter__(self) -> Iterator[FileOrDirectory]:
        return iter(self.__titles())

    @cached(cache=TTLCache(maxsize=1024, ttl=3000))
    def __titles(self) -> List[FileOrDirectory]:
        page = requests.get(
            "%s/last?page=%d&quantity=%d" % (self.__config.api_url, self.__number, self.__limit))
        series = json.loads(page.text)
        titles = [TitleDirectory("%02d %s" % (i, s['title']), s['id'], self.__config) for i, s in
                  enumerate(series['data'], start=1)]
        return titles


class Search(Directory):

    def __init__(self, name: str, field: str, config: Configuration):
        Directory.__init__(self, name)
        self.__history = dict()
        self.__field = field
        self.__config = config

    def __iter__(self) -> Iterator[FileOrDirectory]:
        return iter(self.__history.values())

    def find(self, path: str) -> 'FileOrDirectory':
        if path == '':
            return self

        path_listed = path.split(os.sep)
        search_query = path_listed.pop(0)
        if search_query not in self.__history:
            search_title = SearchTitle(self.__field, search_query, self.__config)
            self.__history[search_query] = Directory(search_query, search_title)
        deeper_path = os.sep.join(path_listed)
        return self.__history[search_query].find(deeper_path)


class Genres(Directory):

    def __init__(self, name: str, config: Configuration):
        Directory.__init__(self, name)
        self.__items = dict()
        self.__config = config

    def __iter__(self) -> Iterator[FileOrDirectory]:
        return iter(self.__genres())

    @cached(cache=TTLCache(maxsize=1024, ttl=3000))
    def __genres(self):
        page = requests.get("%s/genres" % self.__config.api_url)
        data = json.loads(page.text)
        return [genre for genre in data.values()]

    def find(self, path: str) -> 'FileOrDirectory':
        if path == '':
            return self

        path_listed = path.split(os.sep)
        genre = path_listed.pop(0)
        if genre not in self.__genres():
            raise FuseOSError(errno.ENOENT)

        if genre not in self.__items:
            self.__items[genre] = Directory(genre, SearchTitle(SearchTitle.FIELD_GENRE, genre, self.__config))
        deeper_path = os.sep.join(path_listed)
        return self.__items[genre].find(deeper_path)


class Favorites(Directory):

    def __init__(self, name: str, config: Configuration):
        Directory.__init__(self, name)
        self.__config = config

    def __iter__(self) -> Iterator[FileOrDirectory]:
        return iter(self.__titles())

    @cached(cache=TTLCache(maxsize=1024, ttl=3000))
    def __titles(self) -> List[FileOrDirectory]:
        try:
            token = self.__config.token
        except GetTokenError as err:
            return [File('error.txt', str(err))]
        else:
            page = requests.post("%s/favorites" % self.__config.api_url, {'token': token})
            series = json.loads(page.text)
            titles = [TitleDirectory("%02d %s" % (i, s['title']), s['id'], self.__config) for i, s in
                      enumerate(series['data'], start=1)]
            return titles


class All(Directory):

    def __init__(self, name: str, config: Configuration):
        Directory.__init__(self, name)
        self.__config = config
        self.__limit = config.limit

    def __iter__(self) -> Iterator[FileOrDirectory]:
        return iter(self.__pages())

    @cached(cache=TTLCache(maxsize=1024, ttl=3000))
    def __pages(self) -> List[FileOrDirectory]:
        page = requests.get("%s/last?page=1&quantity=%d" % (self.__config.api_url, self.__limit))
        series = json.loads(page.text)
        if len(series['data']) < self.__limit:
            self.__limit = len(series['data'])
        last_page = series['state']['count'] // self.__limit + 1
        pages = [Page("%03d" % page, page, self.__config) for page in range(1, last_page + 1)]
        return pages


class Root(Directory):

    def __init__(self, config: Configuration):
        directories = [
            Page('latest', 1, config),
            All('all', config),
            Genres('genres', config),
            Directory('search', [
                Search('by-name', SearchTitle.FIELD_NAME, config),
                Search('by-category', SearchTitle.FIELD_NAME, config),
                Search('by-year', SearchTitle.FIELD_YEAR, config)
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
    options.setdefault('fsname', "doc.org-%s-fuse" % arguments.quality)
    options.setdefault('conf', arguments.configuration)
    conf = Configuration(options['conf'], arguments.quality)
    del options['conf']

    mount(Root(conf), arguments.path, **options)
