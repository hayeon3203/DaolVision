# CC0 Korean narrator reference

The default video narrator reference is assembled from pronunciation recordings
by Lingua Libre speaker `CHK2605` on Wikimedia Commons.

- Source category:
  <https://commons.wikimedia.org/wiki/Category:Lingua_Libre_pronunciation_by_CHK2605>
- Author/recorder: `CHK2605`
- Language: Korean
- License: Creative Commons CC0 1.0 Universal
- License text: <https://creativecommons.org/publicdomain/zero/1.0/>

Each source file page states that the speaker and recorder are `CHK2605` and
that the recording is dedicated under CC0, permitting copying, modification,
distribution, performance, and commercial use without permission. The local
reference is rebuilt with:

```bash
./tts/chatterbox/build_cc0_narrator_reference.sh
```

The downloaded files, API manifest, and generated `reference.wav` are stored
under the Git-ignored `private/tts/voices/narrator_cc0/` directory.
