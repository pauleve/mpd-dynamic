# mpd-dynamic - Dynamic playlists for MPD using Spotify

This script will auto-complete your MPD playlist using track recommendations from Spotify.

## Installation

```
pip install https://github.com/pauleve/mpd-dynamic/archive/main.zip
```

## Configuration

You will need to register your app at Spotify Dashboard to get the credentials necessary to make authorized calls (a client id and client secret).

Then, create a file `~/.config/mpd_dynamicrc`:
```cfg
[spotify]
id = xxxx  # client id
secret = xxx # client secret
limit = 30 # increase if you have trouble finding local files matching recommendations

[mpd]
host = localhost # default
port = 6600 # default
password = music # optional

[playlist]
threshold = 10 # if the remaining number of tracks is less than threshold, it will be completed
extend = 3 # how many tracks to add (maximum)
```

## Usage

Simply launch the command
```
mpd-dynamic
```
Stop with <kbd>Ctrl+c</kbd>

## Acknowledgement

Mainly inspired by https://github.com/bboggess/mpdynamic
