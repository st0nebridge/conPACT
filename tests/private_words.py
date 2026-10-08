"""
@module tests.private_words
@description Finds the vocabulary of the maintainer's private setup in a text:
             the names of the workflows and process acronyms conPACT was built
             under, and the private project and machine names that once sat in
             its records and test data. None of it means anything to a reader of
             the published repository (D-20260923-047, D-20261002-062).
             The words are kept as SHA-256 digests, not as text, because this
             file is published too: a list that spelled them out would put back
             the very words it keeps out. Acronyms match only as written in
             capitals, so an ordinary "cap" stays usable; the other words match
             in any case.
@input      a text
@output     found(text): the private words in it, as written, in a set
@dependencies stdlib: hashlib, re
"""
import hashlib
import re

# The first 16 hex digits of each word's SHA-256.
EXACT = {
    "204164d223b35aab", "117a6af19f075d3a", "4270d85a706b5108", "b932825fca6de767",
    "1a2579921f527d2c", "31e3cbd5c7bd25c4", "d581d777c428770c", "35c14d71944d3f4b",
}
FOLDED = {
    "17b725e47e8419fd", "f5d61de0aa3eb3fb", "b1ece0f3fb4f7be0", "0ec18b5c06726b70",
    "976a0c30938a5729", "52f0b437261a7139", "d13ccbb664e1f6fa", "c940cebe91d095e0",
}

# A word on its own, and a hyphenated compound whole: a machine name keeps its
# hyphen, while an acronym prefixed to a word is still seen on its own.
WORD = re.compile(r"[A-Za-z0-9_]+")
COMPOUND = re.compile(r"[A-Za-z0-9_]+(?:-[A-Za-z0-9_]+)+")


def digest(word):
    return hashlib.sha256(word.encode("utf-8")).hexdigest()[:16]


def found(text):
    words = set(WORD.findall(text)) | set(COMPOUND.findall(text))
    return {word for word in words
            if digest(word) in EXACT or digest(word.lower()) in FOLDED}
