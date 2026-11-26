"""The menu-cleaning rule: drop lines that are mostly links, keep everything else. Made-up text only."""
from stringer import clean


def test_menus_teasers_and_bare_links_are_dropped():
    for line in ["* [World](https://x.example/world) * [Sport](https://x.example/sport)",
                 "[Read more: Mayor opens new bridge in the north of the city](https://x.example/a)",
                 "- [Other story about a different event entirely, with many words in it.](https://x.example/b)",
                 "https://x.example/share",
                 "![photo](https://x.example/p.jpg)"]:
        assert clean.is_menu(line), line


def test_article_lines_are_kept():
    for line in ["The council voted 7 to 2 on Tuesday to approve the bridge.",
                 "The [majority of the cases](https://x.example/c) remain in the northern provinces, officials said.",
                 "## Background",
                 "",
                 "Photo: a crowd outside the council building"]:
        assert not clean.is_menu(line), line


def test_clean_keeps_lines_word_for_word():
    text = "* [Home](h) * [News](n)\nThe council voted on Tuesday.\n[Next story](s)\nIt passed 7 to 2."
    assert clean.clean(text) == "The council voted on Tuesday.\nIt passed 7 to 2."
    assert clean.kept_lines(text) == [1, 3]


def test_runs_ignore_menus_and_link_markup():
    a = "* [Home](h) * [News](n)\nOne two three four five six seven eight nine."
    b = "One two three four five six [seven eight](z) nine."
    assert clean.runs(a) == clean.runs(b) == {"one two three four five six seven eight",
                                               "two three four five six seven eight nine"}
