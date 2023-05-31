import os
import base64
import requests
import datetime
import json
from urllib.parse import urlparse, parse_qs
import youtube_dl
import pandas as pd


from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv('/Users/dodo/Library/CloudStorage/OneDrive-JCWResourcing/Development/Projects/Youtube Project/Youtube_Spoitfy/Youtube_Spotify/.env')

client_id = os.getenv('clientID')
client_secret = os.getenv('client_Secret')
youtube_api_key = os.getenv('youtube_api_key')
spotify_user_id = os.getenv('username')

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
                    video = youtube_dl.YoutubeDL({}).extract_info(youtube_url, download=False)
                    song_name = video["track"]
                    artist = video["artist"]
                except Exception as e:
                    print(f"Error occurred with URL: {youtube_url}")
                    print(str(e))
                    continue

                if song_name is not None and artist is not None:
                    # save all important info and skip any missing song and artist
                    self.all_song_info[video_title] = {
                        "youtube_url": youtube_url,
                        "song_name": song_name,
                        "artist": artist,

                        # add the uri, easy to get song to put into playlist
                        "spotify_uri": self.search_for_song_uri(song_name, artist)
                    }

    def get_token(self):
        auth_string = f"{client_id}:{client_secret}"
        auth_bytes = auth_string.encode("utf-8")
        auth_base64 = str(base64.b64encode(auth_bytes), "utf-8")

        url = 'https://accounts.spotify.com/api/token'
        token_data = {
            "grant_type": "client_credentials"
        }
        token_headers = {
            "Authorization": f"Basic {auth_base64}",
            "Content-Type": "application/x-www-form-urlencoded"
        }

        result = requests.post(url, headers=token_headers, data=token_data)
        valid_request = result.status_code in range(200, 299)

        if valid_request:
            now = datetime.datetime.now()
            token_response_data = result.json()
            access_token = token_response_data['access_token']
            expires_in = token_response_data['expires_in']
            expires = now + datetime.timedelta(seconds=expires_in)
            return access_token
        else:
            raise TypeError('Oops, token not working')

    def get_auth_header(self):
        return {"Authorization": "Bearer " + self.token}

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
        query = f"?q=track%3a{song_name}+artist%3A{artist}&type=artist%2Ctrack"
        query_url = url + query

        result = requests.get(query_url, headers=headers)
        json_result = json.loads(result.content)["tracks"]["items"]
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

        # collect all of uri
        uris = [info["spotify_uri"]
                for song, info in self.all_song_info.items()]
        
        # Make the request to the Spotify API
        url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
        headers = self.get_auth_header()
        data = json.dumps({"uris": song_uris})
        response = requests.post(url, headers=headers, data=data)

        # check for valid response status
        if response.status_code != 200:
            raise Exception(f"Failed to add songs to playlist. Status code: {response.status_code}")

        response_json = response.json()
        print(f"Successfully added songs to playlist: {playlist_id}")
        return response_json
        
if __name__ == '__main__':
    playlist_url = input("Please input your YouTube playlist URL: ")
    cp=CreatePlaylist(playlist_url)
    cp.add_song_to_playlist()