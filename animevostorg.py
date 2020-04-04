#!/usr/bin/env python3

'''
Created on Oct 30, 2018

@author: Dmytro Dubrovny <dubrovnyd@gmail.com>
'''

from typing import List, Iterator
from cachetools import cached, TTLCache
from webfs import File, Directory, Playlist, PlaylistItem, FileOrDirectory
import json
import os
import requests
import toml

API_URL = 'https://api.animevost.org/v1'


class GetTokenError(Exception):

    def __init__(self, message: str = ''):
        self.__message = message

    @property
    def message(self) -> str:
        return self.__message


class SearchTitle:
    FIELD_GENRE = 'gen'
    FIELD_NAME = 'name'
    FIELD_CATEGORY = 'cat'
    FIELD_YEAR = 'year'

    def __init__(self, field: str, value: str, quality: str):
        self.__field = field
        self.__value = value
        self.__quality = quality

    def __iter__(self) -> Iterator[FileOrDirectory]:
        return iter(self.__search())

    @cached(cache=TTLCache(maxsize=1024, ttl=3000))
    def __search(self) -> List[FileOrDirectory]:
        page = requests.post("%s/search" % API_URL, {self.__field: self.__value})
        series = json.loads(page.text)
        series.setdefault('data', [])
        titles = [TitleDirectory("%02d %s" % (i, s['title']), s['id'], self.__quality) for i, s in
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

    @staticmethod
    def qualities() -> List[str]:
        return ['std', 'hd']


class TitleDirectory(Directory):

    def __init__(self, name: str, title_id: int, quality: str):
        Directory.__init__(self, name)
        self.__title_id = title_id
        self.__quality = quality

    def __iter__(self):
        return iter(self.__playlist())

    @cached(cache=TTLCache(maxsize=1024, ttl=3000))
    def __playlist(self) -> List[Playlist]:
        page = requests.post("%s/playlist" % API_URL, {'id': self.__title_id}, None)
        series_data = json.loads(page.text)
        series = []
        for episode_data in series_data:
            if self.__quality in episode_data and requests.head(episode_data[self.__quality]).ok:
                series.append(Episode(episode_data['name'], episode_data[self.__quality]))
            else:
                for quality in Episode.qualities():
                    if quality in episode_data and requests.head(episode_data[quality]).ok:
                        series.append(Episode(episode_data['name'], episode_data[quality]))
                        break
                pass
        sorted_series = sorted(series)
        playlists = [Playlist(episode.title, sorted_series[i:]) for i, episode in enumerate(sorted_series, start=1)]
        return playlists


class Page(Directory):

    def __init__(self, name: str, number: int, quality: str, limit: int = 99):
        Directory.__init__(self, name)
        self.__number = number
        self.__quality = quality
        self.__limit = limit

    def __iter__(self) -> Iterator[FileOrDirectory]:
        return iter(self.__titles())

    @cached(cache=TTLCache(maxsize=1024, ttl=3000))
    def __titles(self) -> List[FileOrDirectory]:
        page = requests.get("%s/last?page=%d&quantity=%d" % (API_URL, self.__number, self.__limit))
        series = json.loads(page.text)
        titles = [TitleDirectory("%02d %s" % (i, s['title']), s['id'], self.__quality) for i, s in
                  enumerate(series['data'], start=1)]
        return titles


class LogSearchDirectory(Directory):

    def __init__(self, name: str, field: str, quality: str):
        Directory.__init__(self, name)
        self.__field = field
        self.__quality = quality
        self.__history = dict()

    def __iter__(self) -> Iterator[FileOrDirectory]:
        return iter(self.__history.values())

    def find(self, path: str) -> 'FileOrDirectory':
        if path == '':
            return self

        path_listed = path.split(os.sep)
        search_query = path_listed.pop(0)
        if search_query not in self.__history:
            self.__history[search_query] = Directory(search_query,
                                                     SearchTitle(self.__field, search_query, self.__quality))
        deeper_path = os.sep.join(path_listed)
        return self.__history[search_query].find(deeper_path)


class GenresSearchDirectory(LogSearchDirectory):

    def __init__(self, name: str, quality: str):
        LogSearchDirectory.__init__(self, name, SearchTitle.FIELD_GENRE, quality)

    def __iter__(self) -> Iterator[FileOrDirectory]:
        return iter(self.__genres())

    @cached(cache=TTLCache(maxsize=1024, ttl=3000))
    def __genres(self):
        page = requests.get("%s/genres" % API_URL)
        data = json.loads(page.text)
        return [genre for genre in data.values()]


class Favorites(Directory):

    def __init__(self, name: str, quality: str, username: str, password: str):
        Directory.__init__(self, name)
        self.__quality = quality
        self.__username = username
        self.__password = password

    def __iter__(self) -> Iterator[FileOrDirectory]:
        return iter(self.__titles())

    @cached(cache=TTLCache(maxsize=1024, ttl=3000))
    def __titles(self) -> List[FileOrDirectory]:
        try:
            token = self.__token()
        except GetTokenError as err:
            return [File('error.txt', err.message)]
        else:
            page = requests.post("%s/favorites" % API_URL, {'token': token})
            series = json.loads(page.text)
            titles = [TitleDirectory("%02d %s" % (i, s['title']), s['id'], self.__quality) for i, s in
                      enumerate(series['data'], start=1)]
            return titles

    @cached(cache=TTLCache(maxsize=1024, ttl=30000))
    def __token(self) -> str:
        page = requests.post("%s/gettoken" % API_URL, {'user': self.__username, 'pass': self.__password})
        data = json.loads(page.text)
        if data['status'] == 'ok':
            return data['token']
        raise GetTokenError(data['error'])


class AllPages(Directory):

    def __init__(self, name: str, quality: str):
        Directory.__init__(self, name)
        self.__limit = 99
        self.__quality = quality

    def __iter__(self) -> Iterator[FileOrDirectory]:
        return iter(self.__pages())

    @cached(cache=TTLCache(maxsize=1024, ttl=3000))
    def __pages(self) -> List[FileOrDirectory]:
        page = requests.get("%s/last?page=1&quantity=%d" % (API_URL, self.__limit))
        series = json.loads(page.text)
        if len(series['data']) < self.__limit:
            self.__limit = len(series['data'])
        last_page = series['state']['count'] // self.__limit + 1
        pages = [Page("%03d" % page, page, self.__quality, self.__limit) for page in range(1, last_page + 1)]
        return pages


class Root(Directory):

    def __init__(self, quality: str, conf: str):
        directories = [
            Page('latest', 1, quality),
            AllPages('all', quality),
            Directory('search', [
                LogSearchDirectory('by-name', SearchTitle.FIELD_NAME, quality),
                GenresSearchDirectory('by-genre', quality),
                LogSearchDirectory('by-year', SearchTitle.FIELD_YEAR, quality)
            ])
        ]
        if os.path.isfile(conf):
            config = toml.load(conf)
            if all(k in config for k in ('username', 'password')):
                directories.append(Favorites('favorites', quality, config['username'], config['password']))
        Directory.__init__(self, '', directories)


if __name__ == '__main__':
    from webfs import mount, parse_options, argument_parser

    parser = argument_parser()
    parser.add_argument('quality', type=str, help='Video quality', choices=Episode.qualities())
    parser.add_argument('path', type=str, help='Target path')
    parser.add_argument('-c', '--configuration', type=str, help='Path to config file', default='')

    arguments = parser.parse_args()
    options = parse_options(arguments)
    options.setdefault('fsname', "animevost.org-%s-fuse" % arguments.quality)
    options.setdefault('conf', arguments.configuration)
    configuration = options['conf']
    del options['conf']

    mount(Root(arguments.quality, configuration), arguments.path, **options)
