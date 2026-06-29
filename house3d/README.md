# House 3D Walkthrough

A first-person 3D walkthrough generated from the architectural CAD floor plan
(`NGUYEN_AD.dwg`). Walls are extruded to 9&nbsp;ft, windows shown as translucent
glass, and each room is labelled.

## Use it

Open **`walkthrough.html`** in any modern desktop browser (Chrome/Edge/Firefox/Safari).
Click to start, then:

| Control | Action |
|---|---|
| `W` `A` `S` `D` / arrows | Move |
| Mouse | Look around |
| `Shift` | Run |
| `Q` / `E` (or `Space`) | Crouch / rise |
| `Esc` | Release mouse |

The file is self-contained (Three.js loads from a CDN, so it needs internet
the first time). The floor-plan geometry is embedded directly in the HTML.

## The home

Single-storey plan: garage, two bedrooms, master suite (bedroom + bath),
kitchen, two wardrobes/closets, baths, hall, utility, family / dining /
living rooms, plus a 45&deg; angled wing. Footprint ≈ 131 ft × 80 ft.

## How it was built (reproducible pipeline)

The source DWG (AutoCAD 2010) was processed entirely with open tooling:

1. **`convert.mjs`** — `@mlightcad/libredwg-web` (WASM build of LibreDWG)
   converts `*.dwg` → `*.dxf`.
2. **`extract_scene.py`** — `ezdxf` parses the DXF, isolates the main floor
   plan by spatial region, and pulls geometry by layer:
   - walls: `EXWALLS`, `NEWALLS1`, `NEWALLS2`
   - windows: `NEWINDOW1`, `EXWINDOW`, `B2WINDOWS`
   - doors: `EXDOORS`  · room names: `ROOMNAME` text
   Coordinates are centred and converted from inches → feet → `floorplan_data.json`.
3. **`simplify.py`** — optional grid-snap + de-duplication for a lighter mesh.
4. The walls/windows are extruded into vertical quads in Three.js and rendered
   with first-person `PointerLockControls`.

### Re-run
```bash
npm i @mlightcad/libredwg-web
node convert.mjs                 # dwg -> house.dxf
pip install ezdxf
python3 extract_scene.py         # dxf -> floorplan_data.json
```

## Notes / limitations
- Walls come from the 2D line-work, so they read as thin partitions (the plan's
  double-lines give them apparent thickness). Door openings appear naturally as
  gaps; door leaves/swings are not modelled.
- Only the main floor plan is built. The DWG also contains elevation views, a
  roof plan and a rotated site copy that aren't part of the walkthrough.
- This is a personal visualisation of the owner's own home, not a
  reproduction of the architect's drawing set.
