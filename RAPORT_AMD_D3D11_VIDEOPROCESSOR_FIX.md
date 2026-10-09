# Raport: naprawa AMD D3D11 VideoProcessor

Data: 2026-10-09  
Projekt: SportCamComparator  
GPU: AMD Radeon (TM) Graphics, VendorId=0x1002, DeviceId=0x15e7, LUID 00000000:0000b3e4

## Przyczyna awarii

Na źródłach DJI_20261005062901_0004_D.MP4 i GX010344.MP4 decoder D3D11VA zwracał powierzchnie P010 10-bit (sw_format=p010le, DXGI_FORMAT_P010=104), 3840×2176, array size 20, bind flags 0x200.

AMD obsługiwał osobno NV12, P010 i BGRA8, raportował MaxInputStreams=52 i capability rotacji. Awaria 0x80004005 następowała przy bezpośrednim przekazaniu filmów P010 i tekstury BGRA telemetrii do jednego VideoProcessorBlt. Dwa strumienie wideo bez overlay przechodziły; włączenie overlay w bezpośrednim wariancie VP odtwarzało błąd. Obrót 180° nie był przyczyną.

Drugi problem dotyczył braku jawnego ColorSpace1 dla strumieni wejściowych. Źródła miały różne parametry: DJI BT.709 limited, GoPro BT.2020/HLG full. Domyślny stan drivera powodował różowo-fioletowy obraz. Obsługa per wejście musi korzystać z metadanych źródła.

## Naprawa

Na AMD dwa strumienie P010 przechodzą przez Video Processor do pośredniej powierzchni BGRA. Metadane barw każdego strumienia są ustawiane jawnie. Rotacja jest wykonywana przed nakładką. Telemetria Direct2D pozostaje teksturą BGRA, ale jest łączona przez shader D3D11 z prawidłowym premultiplikowanym alpha blendingiem. Drugi przebieg VP tworzy NV12 dla AMF. AMF dostaje oznaczenia wyjściowe BT.709 limited.

Ta ścieżka jest wybrana po VendorId=0x1002; ścieżki NVIDIA, Intel i CPU nie są przepinane na ten shader.

## Diagnostyka sprzętu

- formaty NV12 (103), P010 (104) i BGRA8 (87): wejście/wyjście wspierane przez capability check
- MaxInputStreams=52
- FeatureCaps=0x8e6, rotacja wspierana
- finalny Video Processor w wariantach AMD otrzymuje 2 strumienie wideo
- shader miesza 0 lub 2 tekstury telemetryczne
- oryginalny bezpośredni wariant z BGRA zwracał E_FAIL (0x80004005); po rozdzieleniu etapów VP zwracał S_OK

## Wyniki A–F

Ta sama para źródeł, 3840×2160, próby wykonywane sekwencyjnie. Każda próba dała 30/30 klatek i sukces. Pełnoklatkowe transfery oraz klatki programowe: 0.

| Próba | Obrót | Overlay | Padding | Rezultat |
|---|---:|---:|---:|---|
| A | 0° | brak | brak | PASS, 26.33 FPS |
| B | 180° | brak | brak | PASS, 27.93 FPS |
| C | 0° | dwa | brak | PASS, 28.20 FPS |
| D | 180° | dwa | brak | PASS, 28.47 FPS |
| E | 180° | brak | 3840×2160 | PASS, 27.12 FPS |
| F | 180° | dwa | 3840×2160 | PASS, 27.98 FPS |

Padding został włączony w E/F, lecz źródłowy kompozyt już zajmował całe płótno 3840×2160, więc nie powstała dodatkowa ramka paddingu. Eksport góra/dół z dwoma overlay także przeszedł.

## Długie próby i walidacja

- bez overlay: 30.03 s, 900 klatek, 26.08 FPS;
- z dwoma overlay: 30.03 s, 900 klatek, 25.41 FPS;
- wynik obu: HEVC Main 3840×2160 yuv420p, BT.709 limited; AAC LC stereo 48 kHz;
- full_frame_hwdownload_count=0, full_frame_hwupload_count=0, software_frame_count=0;
- obrót, kompozycja lewo/prawo, kolory, tekst, czarne pasy i góra/dół skontrolowane na klatkach z finalnych MP4;
- anulowanie po 46 klatkach sfinalizowało częściowy plik; następny eksport 1 s przeszedł.

Profil końcowego shadera: COMPOSITOR_MS=1.75 ms, COMPOSITOR_GPU_MS=36.86 ms; cały eksport z overlay osiągnął 25.41 FPS. CPU średnio 32.8% jednego z 16 logicznych procesorów. Dostępny wcześniejszy wynik bez overlay wynosił około 24.9 FPS przy krótkiej próbie, ale długości prób różnią się, więc to nie jest ścisły test A/B. Próbki wykorzystania GPU były zbyt nieliczne i sumowały silniki Windows GPU Engine, aby podać wiarygodny pojedynczy procent.

## Opcje, regresje i ograniczenia

W Opcjach wieloliniowy stderr FFmpeg z nieudanego testu AMF dla 7680×2160 zajmował dużą część dialogu. Opcje pokazują teraz krótką wiadomość z nazwą kodera i docelowym wymiarem; szczegół pozostaje w logu. Karta nadal nie pozwala wybrać Podwójnego 4K, jeśli AMF nie potwierdza danego rozmiaru.

Natywny helper zbudowano ponownie w Release. compileall przeszedł. Pełny pytest: 221 passed, 2 skipped; pominięte przypadki dotyczą GPU nieobecnego na maszynie testowej. NVIDIA Modern i testy CPU przechodzą.

Nie wykonywałem osobnego odczytu powierzchni przed AMF ani próbek Y/Cb/Cr. Nie uruchamiałem również eksportu 7680×2160 po zmianach; bieżący probe legacy AMF dla tego płótna zakończył się błędem i nie należy oznaczać tej opcji jako dostępnej bez udanego testu kodowania. Współczynnik HLG→BT.709 obsługuje Video Processor; nie dodano własnego tone mappingu.

Pełniejszy opis zmienionych plików i wyników obrazu znajduje się w RAPORT_AMD_D3D11_COLOR_AND_OVERLAY_FIX.md.
