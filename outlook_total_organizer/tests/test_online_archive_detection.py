# -*- coding: utf-8 -*-
"""オンラインアーカイブ判定 (OutlookMailManager._find_online_archive_root) のテスト。

実機で確定した事実: ExchangeStoreType は 現行メールボックス=0 / オンラインアーカイブ=1 /
PST(Outlookデータファイル)=3。型値3 (PST) をアーカイブと誤判定しないことを、フェイクのStoresで確認する。
Outlook(COM)・AI・ネットワークには触れない。
"""
import unittest

import _loader


def oto():
    return _loader.load()


class FakeFolder:
    def __init__(self, label):
        self.label = label


class FakeStore:
    def __init__(self, name, stype, store_id=None, raises=False):
        self.DisplayName = name
        self.ExchangeStoreType = stype
        self.StoreID = store_id or ("ID-" + name)
        self._raises = raises
        self.root = FakeFolder("root:" + name)

    def GetRootFolder(self):
        return self.root


class BoomStore:
    """プロパティ参照で例外を投げるストア"""
    @property
    def StoreID(self):
        raise RuntimeError("boom")

    @property
    def DisplayName(self):
        raise RuntimeError("boom")

    @property
    def ExchangeStoreType(self):
        raise RuntimeError("boom")


class FakeStores:
    def __init__(self, items):
        self._items = items
        self.Count = len(items)

    def Item(self, i):
        it = self._items[i - 1]
        if it == "ITEM_ERROR":
            raise RuntimeError("Item(i) failed")
        return it


class FakeNamespace:
    def __init__(self, stores, default_store=None):
        self.Stores = FakeStores(stores)
        self._default = default_store

    def GetDefaultFolder(self, n):
        if self._default is None:
            raise RuntimeError("no default")
        d = self._default

        class _F:
            Store = d
        return _F()


def find(namespace):
    cls = oto().OutlookMailManager
    return cls._find_online_archive_root(object.__new__(cls), namespace)


MAIN = FakeStore("user@example.com", 0)
PST = FakeStore("2023_Q3", 3)
ARCH = FakeStore("オンライン アーカイブ - x@y.com", 1)


class TestOnlineArchiveDetection(unittest.TestCase):
    def test_pst_first_then_online_archive_returns_archive(self):
        ns = FakeNamespace([MAIN, PST, ARCH], default_store=MAIN)
        self.assertIs(find(ns), ARCH.root)

    def test_pst_only_returns_none(self):
        ns = FakeNamespace([MAIN, PST, FakeStore("2024_Q2", 3)], default_store=MAIN)
        self.assertIsNone(find(ns))

    def test_english_name_type1(self):
        s = FakeStore("Online Archive - x", 1)
        ns = FakeNamespace([MAIN, PST, s], default_store=MAIN)
        self.assertIs(find(ns), s.root)

    def test_default_store_excluded(self):
        d = FakeStore("オンライン アーカイブ - default", 1)
        ns = FakeNamespace([d], default_store=d)
        self.assertIsNone(find(ns))

    def test_type1_unrelated_name_is_none(self):
        ns = FakeNamespace([MAIN, FakeStore("Shared", 1)], default_store=MAIN)
        self.assertIsNone(find(ns))

    def test_type1_with_archive_word_is_auxiliary_match(self):
        s = FakeStore("My Archive Box", 1)
        ns = FakeNamespace([MAIN, s], default_store=MAIN)
        self.assertIs(find(ns), s.root)

    def test_type3_with_archive_word_only_not_matched_by_type(self):
        # 型値3(PST)は、表示名がパターンに一致しない限りアーカイブ扱いにしない
        ns = FakeNamespace([MAIN, FakeStore("old archive box", 3)], default_store=MAIN)
        self.assertIsNone(find(ns))

    def test_pst_named_like_archive_matches_by_name(self):
        # 表示名パターン一致は第一判定(型値によらない)
        s = FakeStore("オンライン アーカイブ - copy", 3)
        ns = FakeNamespace([MAIN, s], default_store=MAIN)
        self.assertIs(find(ns), s.root)

    def test_exception_store_does_not_stop_scan(self):
        ns = FakeNamespace([MAIN, BoomStore(), "ITEM_ERROR", PST, ARCH], default_store=MAIN)
        self.assertIs(find(ns), ARCH.root)

    def test_no_default_folder_still_works(self):
        ns = FakeNamespace([PST, ARCH], default_store=None)
        self.assertIs(find(ns), ARCH.root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
