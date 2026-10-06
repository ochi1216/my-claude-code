#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""使い捨てフローのエクスポート(pac solution unpack の出力)を、実測に必要な形へ要約する。

使い捨てフローを GUI で1本作ってエクスポートすると、operationId・パラメータ名・接続参照の
論理名・認証の書き方が JSON に出る。このスクリプトは、その中から実測に必要な部分だけを
順番どおりに並べて表示する。GUID・メールアドレス・URL のホスト名は伏せるため、出力を
そのままチャットへ貼って共有できる(会社の識別子をコミット・共有しないための配慮)。

使い方:

    pac solution export --name ECS_Measure --path ./ECS_Measure.zip
    pac solution unpack --zipfile ./ECS_Measure.zip --folder ./measure_src
    python summarize_export_20261006_01.py ./measure_src

伏せるもの: GUID / メールアドレス / URL のホスト名 / 80文字を超える値(途中で省略)。
伏せないもの: operationId・パラメータ名・式(@...)・接続参照の論理名。
"""

import json
import os
import re
import sys

GUID_RE = re.compile(r"\{?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}?")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"(https?://)([^/\s'\"]+)")
MAX_LEN = 80


def mask(value):
    """値から、会社の識別子になりうる部分を伏せる。"""
    if isinstance(value, str):
        text = GUID_RE.sub("<GUID>", value)
        text = EMAIL_RE.sub("<email>", text)
        text = URL_RE.sub(lambda m: m.group(1) + "<host>", text)
        if len(text) > MAX_LEN:
            text = text[:MAX_LEN] + "...(省略)"
        return text
    if isinstance(value, (dict, list)):
        return mask(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    return value


def ordered_actions(actions):
    """runAfter の依存順(同順位は定義順)に、(名前, アクション)を並べる。入れ子も展開する。"""
    flat = []

    def collect(container, depth):
        remaining = dict(container)
        done = set()
        while remaining:
            ready = [n for n, a in remaining.items()
                     if all(dep in done or dep not in container for dep in a.get("runAfter", {}))]
            if not ready:  # 循環・参照切れがあっても、残りを定義順で出して終わる
                ready = list(remaining)
            for name in ready:
                action = remaining.pop(name)
                done.add(name)
                flat.append((depth, name, action))
                for key in ("actions",):
                    if key in action:
                        collect(action[key], depth + 1)
                if "else" in action:
                    collect(action["else"].get("actions", {}), depth + 1)

    collect(actions, 0)
    return flat


def describe_host(inputs):
    # Compose などは inputs が文字列(式)のことがある
    if not isinstance(inputs, dict):
        return "", ""
    host = inputs.get("host", {})
    return host.get("connectionName", ""), host.get("operationId", "")


def summarize_flow(path):
    with open(path, encoding="utf-8-sig") as fh:
        flow = json.load(fh)
    properties = flow.get("properties", {})
    definition = properties.get("definition", {})
    lines = ["== %s ==" % os.path.basename(path)]

    lines.append("接続参照:")
    for key, ref in properties.get("connectionReferences", {}).items():
        logical = ref.get("connection", {}).get("connectionReferenceLogicalName", "(なし)")
        lines.append("  %s -> %s (runtimeSource=%s)" % (key, logical, ref.get("runtimeSource", "?")))

    for name, trigger in definition.get("triggers", {}).items():
        connection, operation = describe_host(trigger.get("inputs"))
        lines.append("トリガー: %s  type=%s  connection=%s  operationId=%s"
                     % (name, trigger.get("type"), connection, operation))
        inputs = trigger.get("inputs", {})
        for key, value in (inputs.get("parameters") or {}).items():
            lines.append("    %s = %s" % (key, mask(value)))
        if "authentication" in inputs:
            lines.append("    authentication = %s" % mask(inputs["authentication"]))

    lines.append("アクション(実行順):")
    for index, (depth, name, action) in enumerate(ordered_actions(definition.get("actions", {})), 1):
        connection, operation = describe_host(action.get("inputs"))
        head = "%s%2d. %s  type=%s" % ("  " * depth, index, name, action.get("type"))
        if operation:
            head += "  connection=%s  operationId=%s" % (connection, operation)
        lines.append(head)
        inputs = action.get("inputs")
        if isinstance(inputs, dict) and "parameters" in inputs:
            for key, value in (inputs["parameters"] or {}).items():
                lines.append("%s      %s = %s" % ("  " * depth, key, mask(value)))
            if "authentication" in inputs:
                lines.append("%s      authentication = %s" % ("  " * depth, mask(inputs["authentication"])))
        elif action.get("type") in ("Compose", "Query", "If", "SetVariable"):
            lines.append("%s      inputs = %s" % ("  " * depth, mask(inputs if inputs is not None else action.get("expression"))))
    return "\n".join(lines)


def summarize(folder):
    paths = []
    for dirpath, _dirs, files in os.walk(folder):
        for file in files:
            if file.endswith(".json") and os.path.basename(dirpath) == "Workflows":
                paths.append(os.path.join(dirpath, file))
    if not paths:
        raise SystemExit("Workflows フォルダ内のフロー定義(.json)が見つかりません: %s" % folder)
    return "\n\n".join(summarize_flow(p) for p in sorted(paths))


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    print(summarize(sys.argv[1]))


if __name__ == "__main__":
    main()
