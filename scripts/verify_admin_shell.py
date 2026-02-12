#!/usr/bin/env python3
"""Verify that frontend/admin.html satisfies frontend/admin.js shell requirements."""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Iterable
from urllib.parse import urlparse


RE_GET_ELEMENT_BY_ID = re.compile(r"getElementById\(\s*['\"]([^'\"]+)['\"]\s*\)")
RE_QUERY_SELECTOR = re.compile(r"querySelector(?:All)?\(\s*['\"]([^'\"]+)['\"]\s*\)")

EXPLICIT_REQUIRED_SELECTORS = {
    "[data-admin-tab]",
    ".admin-danger-zone",
    "#admin-panel-service",
    "#admin-panel-notifications",
    "#admin-panel-audit",
    "#confirm-modal-backdrop",
    "#confirm-modal",
    "#confirm-modal-title",
    "#confirm-modal-message",
    "#confirm-modal-require-wrap",
    "#confirm-modal-require-label",
    "#confirm-modal-require-input",
    "#confirm-modal-cancel-btn",
    "#confirm-modal-confirm-btn",
}

EXPECTED_TAB_VALUES = {"service", "notifications", "audit"}


@dataclass
class NodeRecord:
    kind: str
    index: int
    attrs: dict[str, str]


class AdminHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.data_admin_tabs: set[str] = set()
        self.class_tokens: set[str] = set()
        self.nodes: list[NodeRecord] = []
        self._node_index = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._record(tag, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._record(tag, attrs)

    def _record(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict: dict[str, str] = {}
        for key, value in attrs:
            if value is None:
                continue
            attrs_dict[key] = value

        if "id" in attrs_dict:
            self.ids.add(attrs_dict["id"].strip())

        if "data-admin-tab" in attrs_dict:
            self.data_admin_tabs.add(attrs_dict["data-admin-tab"].strip())

        class_attr = attrs_dict.get("class", "")
        for token in class_attr.split():
            if token:
                self.class_tokens.add(token)

        if tag in {"link", "script"}:
            self.nodes.append(NodeRecord(kind=tag, index=self._node_index, attrs=attrs_dict))
        self._node_index += 1


def normalize_asset_path(value: str) -> str:
    parsed = urlparse(value)
    path = parsed.path or ""
    return pathlib.PurePosixPath(path).name.lower()


def extract_required_ids(js_source: str) -> set[str]:
    return {match.group(1) for match in RE_GET_ELEMENT_BY_ID.finditer(js_source)}


def extract_required_query_selectors(js_source: str) -> set[str]:
    discovered = {match.group(1) for match in RE_QUERY_SELECTOR.finditer(js_source)}
    required = set(EXPLICIT_REQUIRED_SELECTORS)

    for selector in discovered:
        if selector in EXPLICIT_REQUIRED_SELECTORS:
            required.add(selector)
        elif selector.startswith("#admin-panel-"):
            required.add(selector)
        elif selector.startswith("#confirm-modal"):
            required.add(selector)

    return required


def find_asset_nodes(nodes: Iterable[NodeRecord]) -> tuple[NodeRecord | None, NodeRecord | None]:
    stylesheet_node = None
    script_node = None

    for node in nodes:
        if node.kind == "link":
            rel = node.attrs.get("rel", "")
            href = node.attrs.get("href", "")
            if "stylesheet" in rel.lower() and normalize_asset_path(href) == "styles.css":
                stylesheet_node = node
        elif node.kind == "script":
            src = node.attrs.get("src", "")
            if normalize_asset_path(src) == "admin.js":
                script_node = node

    return stylesheet_node, script_node


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify frontend/admin shell contract.")
    parser.add_argument("--html", default="frontend/admin.html", help="Path to admin HTML shell")
    parser.add_argument("--js", default="frontend/admin.js", help="Path to admin JS")
    args = parser.parse_args()

    html_path = pathlib.Path(args.html)
    js_path = pathlib.Path(args.js)

    if not html_path.exists():
        print(f"FAIL: Missing HTML file: {html_path}")
        return 1
    if not js_path.exists():
        print(f"FAIL: Missing JS file: {js_path}")
        return 1

    html_source = html_path.read_text(encoding="utf-8")
    js_source = js_path.read_text(encoding="utf-8")

    html_parser = AdminHTMLParser()
    html_parser.feed(html_source)

    required_ids = extract_required_ids(js_source)
    required_selectors = extract_required_query_selectors(js_source)

    failures: list[str] = []

    missing_ids = sorted(required_ids - html_parser.ids)
    if missing_ids:
        failures.append(
            "Missing ID(s) referenced by admin.js: " + ", ".join(missing_ids)
        )

    missing_tabs = sorted(EXPECTED_TAB_VALUES - html_parser.data_admin_tabs)
    if missing_tabs:
        failures.append(
            "Missing [data-admin-tab] value(s): " + ", ".join(missing_tabs)
        )

    for selector in sorted(required_selectors):
        if selector.startswith("#"):
            selector_id = selector[1:]
            if selector_id not in html_parser.ids:
                failures.append(f"Missing selector target for '{selector}'")
        elif selector == "[data-admin-tab]":
            if not html_parser.data_admin_tabs:
                failures.append("Missing any [data-admin-tab] element")
        elif selector.startswith("."):
            class_name = selector[1:]
            if class_name not in html_parser.class_tokens:
                failures.append(f"Missing selector target for '{selector}'")

    stylesheet_node, script_node = find_asset_nodes(html_parser.nodes)
    if not stylesheet_node:
        failures.append("Missing stylesheet include for styles.css")
    if not script_node:
        failures.append("Missing script include for admin.js")

    if stylesheet_node and script_node and stylesheet_node.index > script_node.index:
        failures.append("styles.css link must appear before admin.js script tag")

    if failures:
        print("FAIL: admin shell verification failed")
        for item in failures:
            print(f" - {item}")
        return 1

    print("PASS: admin shell verification passed")
    print(f" - IDs discovered in HTML: {len(html_parser.ids)}")
    print(f" - getElementById refs in JS: {len(required_ids)}")
    print(f" - data-admin-tab values: {', '.join(sorted(html_parser.data_admin_tabs))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
