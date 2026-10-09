"""
gpmf_discovery.py – skrypt diagnostyczny do podejrzenia struktury GPMF w pliku MP4.

Uruchom:
    python gpmf_discovery.py ścieżka/do/pliku.MP4
"""

import sys
import json
from pathlib import Path

# Dodaj katalog scr do ścieżki
sys.path.insert(0, str(Path(__file__).parent))

from telemetry_gpmf_new import (
    extract_gpmf,
    parse_gpmf,
    parse_gpmf_tree,
    extract_all_streams,
    gpmf_to_full_json,
)


def print_flat(parsed):
    """Wydrukuj płaską listę (key, value) z pominięciem dużych blobów."""
    print("=" * 60)
    print("PŁASKI PARSER – wszystkie klucze w kolejności:")
    print("=" * 60)
    for key, val in parsed:
        # Pomiń długie listy/dane – pokaż tylko typ i rozmiar
        if isinstance(val, (list, tuple)) and len(val) > 10:
            print(f"  {key:6s}  [lista {len(val)} elem.]  typ={type(val[0]).__name__ if val else '?'}")
        elif isinstance(val, bytes) and len(val) > 20:
            print(f"  {key:6s}  [blob {len(val)} bajtów]")
        else:
            print(f"  {key:6s}  {val!r}")


def print_streams(devices):
    """Wydrukuje strukturę strumieni z extract_all_streams – skupiając się na ISOE/SHUT/STMP."""
    print("=" * 60)
    print("STRUMIENIE (extract_all_streams):")
    print("=" * 60)
    for dev_idx, dev in enumerate(devices):
        print(f"\n--- Urządzenie {dev_idx}: id={dev.get('device_id')} name={dev.get('device_name')}")
        streams = dev.get("streams", {})
        for sname, sdata in streams.items():
            print(f"\n  Stream: {sname}")
            meta = sdata.get("_meta", {})
            if meta:
                print(f"    _meta: {json.dumps(meta, default=str, indent=6)}")
            for k, v in sdata.items():
                if k == "_meta":
                    continue
                if isinstance(v, (list, tuple)):
                    if len(v) > 8:
                        print(f"    {k:6s}: [{len(v)} wartości] {v[:4]}...{v[-4:]}")
                    else:
                        print(f"    {k:6s}: {v}")
                else:
                    print(f"    {k:6s}: {v}")


def main():
    if len(sys.argv) < 2:
        print("Użycie: python gpmf_discovery.py <plik.mp4>")
        sys.exit(1)

    video = sys.argv[1]
    print(f"Analizuję: {video}\n")

    # --- 1. Płaski parser ---
    try:
        data = extract_gpmf(video)
        print(f"Surowe GPMF: {len(data)} bajtów\n")
    except Exception as e:
        print(f"BŁĄD ekstrakcji GPMF: {e}")
        sys.exit(1)

    parsed = parse_gpmf(data)
    
    # Filtruj tylko interesujące klucze
    interesting = {"ISOE", "SHUT", "STMP", "TSMP", "SCAL", "SIUN", "UNIT", "DVID", "DVNM", "STNM", "STRM", "DEVC"}
    print("-- INTERESUJĄCE KLUCZE --")
    for key, val in parsed:
        if key in interesting:
            if isinstance(val, (list, tuple)) and len(val) > 10:
                print(f"  {key:6s}  [lista {len(val)} elem.] pierwsze 5: {val[:5]}")
            elif isinstance(val, bytes) and len(val) > 20:
                print(f"  {key:6s}  [blob {len(val)} bajtów]")
            else:
                print(f"  {key:6s}  {val!r}")
    
    # Wszystkie klucze w oryginalnej kolejności
    print("\n-- WSZYSTKIE KLUCZE (kolejność) --")
    for key, val in parsed:
        if isinstance(val, (list, tuple)) and len(val) > 10:
            print(f"  {key:6s}  [lista {len(val)} elem.]")
        elif isinstance(val, bytes) and len(val) > 20:
            print(f"  {key:6s}  [blob {len(val)} bajtów]")
        else:
            print(f"  {key:6s}  {val!r}")

    # --- 2. Drzewo / strumienie ---
    print("\n")
    try:
        devices = gpmf_to_full_json(video)
        print_streams(devices)
    except Exception as e:
        print(f"\nBŁĄD parsera drzewiastego: {e}")


if __name__ == "__main__":
    main()
