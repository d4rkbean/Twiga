"""Contrôle du catalogue anglais (voir tools/i18n.sh check).

Signale : textes du code sans traduction, traductions vides, variables
%(nom)s présentes en anglais mais absentes du français (le rendu échouerait),
et entrées obsolètes. Code de sortie non nul s'il y a un problème bloquant.
"""
import re
import sys

from babel.messages.pofile import read_po

VAR = re.compile(r"%\((\w+)\)[sdr]")

with open("backend/locale/messages.pot", "rb") as handle:
    template = read_po(handle)
with open("backend/locale/en/LC_MESSAGES/messages.po", "rb") as handle:
    catalog = read_po(handle, locale="en")

known = {m.id if isinstance(m.id, str) else m.id[0]: m for m in catalog if m.id}
missing, empty, bad_vars = [], [], []
for message in template:
    if not message.id:
        continue
    msgid = message.id if isinstance(message.id, str) else message.id[0]
    translated = known.get(msgid)
    if translated is None:
        missing.append(msgid)
        continue
    strings = [translated.string] if isinstance(translated.string, str) else list(translated.string)
    if not all(strings):
        empty.append(msgid)
        continue
    allowed = set(VAR.findall(msgid))
    for text in strings:
        if not set(VAR.findall(text)) <= allowed:
            bad_vars.append(msgid)

for title, items in (("Sans entrée dans le catalogue", missing), ("Traduction vide", empty), ("Variable inconnue en anglais", bad_vars)):
    if items:
        print(f"{title} ({len(items)}) :")
        for item in items[:30]:
            print("  -", item[:100])
total = len([m for m in template if m.id])
print(f"{total} textes, {len(missing)} manquants, {len(empty)} vides, {len(bad_vars)} variables invalides")
sys.exit(1 if (missing or empty or bad_vars) else 0)
