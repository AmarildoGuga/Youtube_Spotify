# Youtube_Spotify
# CreatePlaylist: Your Ultimate Playlist Transfer Tool

Turn your Youtube playlists into Spotify playlists in an instant with `CreatePlaylist`! This high-grade, easy-to-use Python utility enables users to swiftly convert their favorite YouTube playlists into Spotify ones.

## What is CreatePlaylist?

CreatePlaylist is a robust Python-based tool developed to streamline the process of transferring music from Youtube playlists to Spotify. Designed with simplicity and effectiveness in mind, it not only converts playlists but also fetches detailed song information.

Imagine you're listening to an amazing playlist on YouTube and you'd like to have the same one on Spotify. Manually searching and adding each song is time-consuming, right? CreatePlaylist is your savior in this case, handling all the nitty-gritty details for you. 

## Key Features

1. **Easy Conversion**: Convert your YouTube playlist into a Spotify playlist with minimal user input.
2. **Detailed Song Information**: Fetches song information such as the artist's name, song name, and even the Spotify URI for each track.
3. **Automatic Playlist Creation**: Creates a new Spotify playlist with all the songs from the YouTube playlist.
4. **Track Addition**: Adds all the tracks from the YouTube playlist into the newly created Spotify playlist.

## Installation

1. Clone this repository by running `git clone https://github.com/<YourUserName>/CreatePlaylist.git`
2. Install the required dependencies by running `pip install -r requirements.txt`

## Setup

Before running CreatePlaylist, you'll need to setup some environment variables:
- `clientID`: Your Spotify Application's Client ID
- `client_Secret`: Your Spotify Application's Client Secret
- `youtube_api_key`: Your YouTube API Key
- `username`: Your Spotify Username

You can create a `.env` file at the root of the project and define these variables in it.

## Usage

After setting up, just run `python create_playlist.py`, provide your YouTube playlist URL and see the magic happen.

## Future Enhancements

We are continuously working to improve CreatePlaylist by adding more features and making it more user-friendly. If you have any suggestions or encounter any issues, feel free to open an issue or contribute to the project.

---

Enjoy your music on Spotify just like you do on YouTube, with CreatePlaylist. Happy listening!

---

**Disclaimer:** This project is intended for personal use and educational purposes. Please respect the copyrights of the artists. The developers do not bear any responsibility for misuse of the tool.

---

## License

This project is licensed under the MIT License. Please see the [LICENSE](LICENSE) file for more details.
