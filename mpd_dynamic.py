#!/usr/bin/env python
import mpd
import spotipy
import os
import random
import socket

import requests

import logging
logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO)

from appdirs import user_config_dir
import configparser

cfg_file = os.path.join(user_config_dir(), "mpd_dynamicrc")
config = configparser.ConfigParser()
config.read([cfg_file])

THRESHOLD = 10
EXTEND_LIMIT = 3
if "playlist" in config:
    THRESHOLD = config["playlist"].getint("threshold", THRESHOLD)
    EXTEND_LIMIT = config["playlist"].getint("extend", EXTEND_LIMIT)

LOOKUP_WINDOW = EXTEND_LIMIT*10
if "spotify" in config:
    LOOKUP_WINDOW = config["spotify"].getint("limit", LOOKUP_WINDOW)

class Track:
    def __init__(self, title, artist, album, id=None):
        self.title = title
        self.artist = artist
        self.album = album
        self.id = id

    def __str__(self):
        return f"{self.artist} - {self.title} ({self.album})"

    @classmethod
    def from_spotify(celf, track):
        return celf(track["name"],
                track["artists"][0]["name"],
                track["album"]["name"], track["id"])
    @classmethod
    def from_mpd(celf, track):
        return celf(track["title"], track["artist"], track["album"],
                    track["file"])

class MPDProxy(object):
    def __init__(self):
        self.connect()

    def connect(self):
        self.mpd = mpd.MPDClient()
        self.mpd.timeout = 10
        self.mpd.idletimeout = None
        host = "localhost"
        port = 6600
        password = None
        if "mpd" in config:
            host = config["mpd"].get("host", host)
            port = config["mpd"].getint("port", port)
            password = config["mpd"].get("password", "")
        self.mpd.connect(host, port)
        if password:
            self.mpd.password(password)

    def __del__(self):
        self.mpd.close()
        self.mpd.disconnect()

    def auto_retry(func):
        def do(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except socket.timeout:
                self.connect()
                return func(self, *args, **kwargs)
        return do

    @auto_retry
    def currentsong(self):
        track = self.mpd.currentsong()
        if track:
            return Track.from_mpd(track)

    @auto_retry
    def count_songs_remaining(self):
        """
        Calculates the number of songs remanining on current playlist
        """
        status = self.mpd.status()
        try:
            i = int(status.get('song', 0))
        except ValueError:
            return THRESHOLD # wait
        return int(status['playlistlength']) - i

    def add_track(self, track):
        logging.info(f"Adding {track}")
        self.mpd.add(track.id)

    def matching_track(self, track):
        matches = [Track.from_mpd(t) for t in self.mpd.find("title", track.title)]
        matches = [t for t in matches if t.artist == track.artist]
        if matches:
            matches0 = [t for t in matches if t.album == track.album]
            if matches0:
                maches = matches0
            return random.choice(matches)

    @auto_retry
    def has_artist(self, artist):
        return self.mpd.count("artist", artist)["songs"] > '0'

    def random_track(self, artist):
        matches = self.mpd.find("artist", artist)
        if matches:
            return Track.from_mpd(random.choice(matches))

class UnboundedHistory(set):
    def _view_track(self, track):
        return (track.artist, track.title)
    def add_track(self, track):
        self.add(self._view_track(track))
    def has_track(self, track):
        return self._view_track(track) in self

class SpotifyRecommendations(object):
    def __init__(self, history):
        SPOTIFY_ID = config["spotify"]["id"]
        SPOTIFY_SECRET = config["spotify"]["secret"]
        creds = spotipy.SpotifyClientCredentials(SPOTIFY_ID, SPOTIFY_SECRET)
        self.spotify = spotipy.Spotify(client_credentials_manager=creds)
        self.history = history
        self.market = config["spotify"].get("market")

    def resolve(self, track):
        artist = track.artist.replace("-"," ")
        title = track.title.replace("-"," ")
        for query in [f"artist:\"{artist}\" {title}",
                f"{artist} {title}"]:
            results = self.spotify.search(q=query, type='track', limit=1,
                        market=self.market)
            results = results['tracks']['items']
            if results:
                break
        if not results:
            logging.warn(f"No spotify track for {track} (query was: {query})")
            return
        logging.debug(f"{track} is {results[0]}")
        return results[0]['id']

    def similar(self, tracks, lib, limit=EXTEND_LIMIT):
        ids = [i for i in map(self.resolve, tracks) if i]
        if not ids:
            return []
        recs = self.spotify.recommendations(seed_tracks=ids,
                    limit=LOOKUP_WINDOW)['tracks']
        recs = list(map(Track.from_spotify, recs))
        random.shuffle(recs)

        selected = []

        def pick(track, mtrack):
            selected.append(mtrack)
            self.history.add(track.id) # .insert(0, track.id)
            self.history.add_track(track)
            return len(selected) == limit

        # 1. prefer new specific tracks
        recs0 = [t for t in recs if t.id not in self.history]
        for track in recs0:
            mtrack = lib.matching_track(track)
            if mtrack:
                if pick(track, mtrack):
                    break
        if selected:
            return selected

        logging.info(f"No local tracks matching recommendations for {tracks}, falling back to artists")

        # 2. fallback to artists
        for track in recs:
            mtrack = lib.random_track(track.artist)
            if mtrack:
                if pick(track, mtrack):
                    break

        if not selected:
            logging.warn(f"No local match for recommendations for {tracks}")

        return selected

class LastFMRecommendations(object):
    def __init__(self, history):
        self.history = history

        LASTFM_API_KEY = "5a854b839b10f8d46e630e8287c2299b";
        self.session = requests.Session()
        self.session.params["api_key"] = LASTFM_API_KEY

    def similar(self, tracks, lib, limit=EXTEND_LIMIT):
        seed_artist = tracks[0].artist
        ret = self.session.get("https://ws.audioscrobbler.com/2.0", params={
            "method": "artist.getSimilar",
            "artist": seed_artist,
            "format": "json",
            "limit": 50})
        ret = ret.json()
        artists = [d["name"] for d in ret["similarartists"]["artist"]]
        selected = []
        for _ in range(limit):
            random.shuffle(artists)
            for artist in artists:
                if lib.has_artist(artist):
                    for i in range(5):
                        track = lib.random_track(artist)
                        if not self.history.has_track(track):
                            self.history.add_track(track)
                            selected.append(track)
                            if len(selected) == limit:
                                return selected
                            break
        return selected

def main():
    random.seed()
    lib = MPDProxy()
    hist = UnboundedHistory()
    feed1 = SpotifyRecommendations(hist)
    feed2 = LastFMRecommendations(hist)
    ratio1 = 2/3
    try:
        while True:
            remaining = lib.count_songs_remaining()
            if remaining < THRESHOLD:
                tracks = [lib.currentsong()]
                if None not in tracks:
                    extend_by = max(THRESHOLD-remaining, EXTEND_LIMIT)
                    ask1 = round(extend_by * ratio1 + 0.5)
                    sel1 = feed1.similar(tracks, lib, limit=ask1)
                    sel2 = feed2.similar(tracks, lib, limit=extend_by-len(sel1))
                    for track in sel1+sel2:
                        lib.add_track(track)
            lib.mpd.idle('playlist', 'player')
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main()
