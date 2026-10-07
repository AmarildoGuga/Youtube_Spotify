import os
import base64
import requests
import datetime
import json
import time
from urllib.parse import urlparse, parse_qs
import yt_dlp as youtube_dl  # maintained fork of youtube_dl, same interface
from spotipy.oauth2 import SpotifyOAuth
import pandas as pd


from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

client_id = os.getenv('clientID')
client_secret = os.getenv('client_Secret')
youtube_api_key = os.getenv('youtube_api_key')
spotify_user_id = os.getenv('username')
redirect_uri = os.getenv('redirect_uri', 'http://127.0.0.1:8888/callback')

api_service_name = "youtube"
api_version = "v3"

youtube = build(api_service_name, api_version, developerKey=youtube_api_key)

class CreatePlaylist:
    def __init__(self, playlist_url):
        self.playlist_id = self.extract_playlist_id(playlist_url)
        self.token = self.get_token()
        self.user_id = spotify_user_id
        self.youtube = youtube
        self.all_song_info = {}
    
    def extract_playlist_id(self, playlist_url):
        try:
            parsed_url = urlparse(playlist_url)
            query_params = parse_qs(parsed_url.query)
            if 'youtube.com' in parsed_url.netloc:
                playlist_id = query_params['list'][0]
                return playlist_id
        except Exception as e:
            print('Invalid URL: Make sure you have uploaded a youtube link a valid playlist:', str(e))
            return None

    def get_video_ids(self, playlist_id):
        video_ids = []
        next_page_token = None
        
        while True:
            request = self.youtube.playlistItems().list(
                part="contentDetails",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=next_page_token
            )
            response = request.execute()

            for item in response['items']:
                video_ids.append(item['contentDetails']['videoId'])

            next_page_token = response.get('nextPageToken')
            if next_page_token is None or len(video_ids) >= 150:
                break

        return video_ids

    def get_video_details(self, video_ids):
        """
        Get video statistics of all videos with given IDs
        Params:
        
        youtube: the build object from googleapiclient.discovery
        video_ids: list of video IDs
        
        Returns:
        Dataframe with videos artist and song
        """
        
        for i in range(0, len(video_ids), 50):  ##Takes all the videos that are present in the playlist
            request = self.youtube.videos().list(
                part="snippet,contentDetails,statistics",
                id = ','.join(video_ids[i:i+50])
            )
            response = request.execute()

            for video in response['items']:
                video_title = video["snippet"]["title"]
                youtube_url = "https://www.youtube.com/watch?v={}".format(
                    video["id"])

                try:
                    # use youtube_dl to collect the song name & artist name
                    video = youtube_dl.YoutubeDL({'quiet': True}).extract_info(youtube_url, download=False)
                    song_name = video.get("track")
                    artist = video.get("artist")
                except Exception as e:
                    print(f"Error occurred with URL: {youtube_url}")
                    print(str(e))
                    continue

                # most videos have no track/artist metadata, so fall back to the video title
                if song_name is None or artist is None:
                    song_name = video_title
                    artist = ""

                if song_name is not None:
                    # save all important info and skip any missing song and artist
                    self.all_song_info[video_title] = {
                        "youtube_url": youtube_url,
                        "song_name": song_name,
                        "artist": artist,

                        # add the uri, easy to get song to put into playlist
                        "spotify_uri": self.search_for_song_uri(song_name, artist)
                    }

    def get_token(self):
        # client credentials can only read, creating a playlist needs the user to log in once
        # (a browser window opens the first time, afterwards the token is cached in .cache)
        auth_manager = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope="playlist-modify-public playlist-modify-private"
        )
        return auth_manager.get_access_token(as_dict=False)

    def get_auth_header(self):
        return {"Authorization": "Bearer " + self.token, "Content-Type": "application/json"}

    def create_playlist(self):
        request_body = json.dumps({
            "name": f"New Playlist: {self.playlist_id}",
            "description": "playlist_url",
            "public": True
        })

        query = f"https://api.spotify.com/v1/users/{self.user_id}/playlists"
        response = requests.post(
            query,
            data=request_body,
            headers=self.get_auth_header()   
        )
        response_json = response.json()

        return response_json['id']

    def search_for_song_uri(self, song_name, artist):    
        url = "https://api.spotify.com/v1/search"
        headers = self.get_auth_header()
        params = {"q": f"{song_name} {artist}".strip(), "type": "track", "limit": 1}

        # retry if spotify says we are going too fast (429), waiting as long as it asks
        for attempt in range(5):
            result = requests.get(url, headers=headers, params=params)
            if result.status_code != 429:
                break
            wait = int(result.headers.get("Retry-After", 5)) + 1
            print(f"Spotify rate limit hit, waiting {wait}s...")
            time.sleep(wait)
        time.sleep(0.3)  # small pause between searches so we stay under the rate limit

        if result.status_code != 200:
            print(f"Spotify search failed ({result.status_code}) for: {song_name}")
            return None
        json_result = result.json().get("tracks", {}).get("items", [])
        if len(json_result) == 0:
            print("No artist or song with this name exists...")
            return None

        uri = json_result[0]["uri"]
        return uri

    def add_song_to_playlist(self):
        video_ids = self.get_video_ids(self.playlist_id)
        self.get_video_details(video_ids)
        
        # Get the playlist id from the create_playlist method
        playlist_id = self.create_playlist()

        # collect all of uri (skip songs that were not found on spotify)
        uris = [info["spotify_uri"]
                for song, info in self.all_song_info.items()
                if info["spotify_uri"] is not None]

        # Make the request to the Spotify API (it accepts at most 100 songs at a time)
        url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
        headers = self.get_auth_header()
        for i in range(0, len(uris), 100):
            data = json.dumps({"uris": uris[i:i+100]})
            response = requests.post(url, headers=headers, data=data)

            # check for valid response status (spotify answers 201 when songs are added)
            if response.status_code not in (200, 201):
                raise Exception(f"Failed to add songs to playlist. Status code: {response.status_code} {response.text}")

        playlist_link = f"https://open.spotify.com/playlist/{playlist_id}"
        print(f"Successfully added {len(uris)} songs to your new playlist:")
        print(playlist_link)
        return playlist_link

if __name__ == '__main__':
    playlist_url = input("Please input your YouTube playlist URL: ")
    cp=CreatePlaylist(playlist_url)
    cp.add_song_to_playlist()