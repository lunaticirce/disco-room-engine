#!/usr/bin/env python3
"""Build the original synthetic ROM used by the public example."""

import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ROM = ROOT / "data" / "disco-rom.db"


def build_rom(path=ROM):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise SystemExit(f"Refusing to overwrite existing ROM: {path}")
    c = sqlite3.connect(path)
    c.executescript(
        """
        CREATE TABLE actors(id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                            description TEXT NOT NULL, talkativeness INTEGER NOT NULL);
        CREATE TABLE temp_table(
          id INTEGER, title TEXT, dialoguetext TEXT, actor INTEGER,
          conversant INTEGER, conversationid INTEGER, difficultypass INTEGER,
          isgroup INTEGER, hascheck INTEGER, sequence TEXT, hasalts INTEGER,
          conditionstring TEXT, userscript TEXT
        );
        CREATE TABLE dlinks(
          originconversationid INTEGER, origindialogueid INTEGER,
          destinationconversationid INTEGER, destinationdialogueid INTEGER,
          isConnector INTEGER DEFAULT 0, priority INTEGER DEFAULT 2
        );
        CREATE TABLE variables(id INTEGER PRIMARY KEY, name TEXT,
                               initialvalue TEXT, description TEXT);
        CREATE TABLE checks(
          conversationid INTEGER, dialogueid INTEGER, isred INTEGER DEFAULT 0,
          difficulty INTEGER, flagname TEXT, forced INTEGER, skilltype TEXT,
          PRIMARY KEY(conversationid, dialogueid)
        );
        CREATE TABLE modifiers(
          conversationid INTEGER, dialogueid INTEGER, variable TEXT,
          modifier INTEGER, tooltip TEXT
        );
        CREATE TABLE alternates(condition TEXT);

        INSERT INTO actors VALUES(0, 'You', '', 0);
        INSERT INTO actors VALUES(1, 'Lamp', '', 0);
        INSERT INTO variables VALUES(1, 'demo.notebook_open', 'False', 'Notebook state');

        INSERT INTO temp_table VALUES
          (1, 'Lamp', 'The lamp hums over a notebook with one clean page.', 1, 0, 1, 0, 0, 0, '0', 0, '', ''),
          (2, 'Open notebook', 'Open the notebook.', 0, 0, 1, 0, 0, 0, '0', 0, '', 'SetVariableValue("demo.notebook_open", true)'),
          (3, 'Leave', '[Leave.]', 0, 0, 1, 0, 0, 0, '0', 0, '', ''),
          (4, 'Page', 'The page waits without judging the first sentence.', 1, 0, 1, 0, 0, 0, '0', 0, '', ''),
          (5, 'Silence', 'The room keeps humming after you step away.', 1, 0, 1, 0, 0, 0, '0', 0, '', '');

        INSERT INTO dlinks VALUES(1, 1, 1, 2, 0, 1);
        INSERT INTO dlinks VALUES(1, 1, 1, 3, 0, 2);
        INSERT INTO dlinks VALUES(1, 2, 1, 4, 0, 1);
        INSERT INTO dlinks VALUES(1, 3, 1, 5, 0, 1);
        """
    )
    c.commit()
    c.close()
    return path


if __name__ == "__main__":
    print(build_rom())
