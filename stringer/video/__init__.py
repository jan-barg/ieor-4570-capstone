"""Module 8, the animation module: module 7's script.json in, a vertical MP4 out.

Code draws and times everything here. One small model call, the voice director (direct.py), adds delivery
tags to the lines before they are voiced; it can never change a word. The steps (design settled Nov 26,
system map module 8):

  1. check.py   check the script against the shared shot catalog; a beat that can't be drawn safely
                becomes a headline card
  2. voice.py   one voice call reads the whole script; its timings are the clock for everything
  3. places.py, people.py   look-ups from data prepared ahead of time
  4. plan.py    the render plan: every beat's frames, blanks, look-ups, marked-word frames and overlays
  5. render.py  hands the plan and the audio to the Remotion project in render/ (on the Mac or Cloud Run)
  6. files.py   checks the MP4, writes the poster, the captions files and the render record

make.py runs them in order for one story folder.
"""
