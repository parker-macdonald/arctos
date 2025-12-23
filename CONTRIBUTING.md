# Contributing

yes yes yes please help!!! there are nowhere near enough hands on this and any help you'd like to provide would be greatly appreciated.

### Bug Reports & Feature Requests

If you aren't a developer but would like to report a bug or request a feature, feel free to do so by creating a new [issue](https://github.com/reid23/arctos/issues) describing your bug/feature. Select the Bug Report or Feature Request templates as appropriate when it prompts you.

### Writing Code

Im not going to write much here; there's no reason Arctos needs to be different from most other open source projects.

If you want to make your own version, fork it and go ahead. do whatever you like.

If you'd like changes merged back into the main version, please:
1. Work on a problem/feature described in a github issue. If there is no issue, make one using the Project template, and fill out everything in depth.
2. write some tests for your code to show that it works (the current test suite is insufficient; don't use it as a reference)
3. write a PR describing everything you changed and any potential high level system impacts. make sure there are no merge conflicts.

Please do note that **this code is not pretty right now**. If you see something and think "why the hell is this the way it is?", you're not crazy, it's just bad code. Please rewrite if you feel so inclined. In general, this codebase has a worrying shortage of:
- tests
- proper docstrings for everything that work with sphinx
- non-stupid code
- input validation
- explanatory bits of text for users
- sensible timezone handling
- and more...

the TLDR here is that this codebase is very much still moving out of the prototype phase and so a) i'd like to keep the standards for new code higher than the quality of the existing code, and b) if you see something horrible, i'd love you forever if you helped fix it.

