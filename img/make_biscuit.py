#!/usr/bin/env python3
"""Draws Biscuit, the scheduler's own cartoon beagle (an original character, v35), in four
poses and renders each to a 240x240 PNG that the assignment email links to from GitHub Pages.
Run from the repo root: python3 img/make_biscuit.py   (needs the preinstalled Playwright)."""
import os, asyncio
from playwright.async_api import async_playwright

HERE = os.path.dirname(os.path.abspath(__file__))

def dog(pose):
    # shared body: cream beagle with a brown saddle and a black nose, drawn flat and friendly
    ear_l = {'wave': 'rotate(-18 62 86)', 'sit': '', 'car': 'rotate(10 62 86)', 'cheer': 'rotate(-30 62 86)'}[pose]
    ear_r = {'wave': 'rotate(18 158 86)', 'sit': '', 'car': 'rotate(-10 158 86)', 'cheer': 'rotate(30 158 86)'}[pose]
    extra = {
        'wave': '<path d="M160 160 q30 -10 38 -42" stroke="#f3e2c4" stroke-width="16" stroke-linecap="round" fill="none"/>'
                '<circle cx="198" cy="116" r="11" fill="#f3e2c4"/>',
        'sit':  '<ellipse cx="86" cy="206" rx="18" ry="9" fill="#f3e2c4"/><ellipse cx="134" cy="206" rx="18" ry="9" fill="#f3e2c4"/>',
        'car':  '<rect x="20" y="176" width="200" height="44" rx="14" fill="#d93025"/>'
                '<circle cx="62" cy="222" r="14" fill="#333"/><circle cx="178" cy="222" r="14" fill="#333"/>'
                '<rect x="150" y="186" width="56" height="18" rx="6" fill="#ffd66b"/>',
        'cheer':'<path d="M60 150 q-28 -20 -22 -52" stroke="#f3e2c4" stroke-width="16" stroke-linecap="round" fill="none"/>'
                '<path d="M160 150 q28 -20 22 -52" stroke="#f3e2c4" stroke-width="16" stroke-linecap="round" fill="none"/>'
                '<circle cx="36" cy="96" r="11" fill="#f3e2c4"/><circle cx="184" cy="96" r="11" fill="#f3e2c4"/>'
                '<text x="104" y="40" font-size="26" text-anchor="middle">🎉</text>',
    }[pose]
    mouth = {'wave': 'M96 126 q14 12 28 0', 'sit': 'M100 126 q10 8 20 0', 'car': 'M94 124 q16 16 32 0', 'cheer': 'M92 122 q18 20 36 0'}[pose]
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 240" width="240" height="240">
<rect width="240" height="240" rx="48" fill="#ffffff"/>
{extra if pose == 'car' else ''}
<ellipse cx="110" cy="170" rx="54" ry="40" fill="#f3e2c4"/>
<path d="M64 160 q46 -36 92 0 v20 q-46 18 -92 0z" fill="#8a5a2b"/>
<g transform="{ear_l}"><ellipse cx="62" cy="96" rx="20" ry="34" fill="#8a5a2b"/></g>
<g transform="{ear_r}"><ellipse cx="158" cy="96" rx="20" ry="34" fill="#8a5a2b"/></g>
<rect x="80" y="136" width="60" height="12" rx="6" fill="#c0392b"/><circle cx="110" cy="146" r="5" fill="#ffd66b"/>
<circle cx="110" cy="98" r="48" fill="#f3e2c4"/>
<path d="M62 80 q48 -40 96 0 q-20 -12 -48 -12 q-28 0 -48 12z" fill="#8a5a2b"/>
<circle cx="94" cy="96" r="7" fill="#222"/><circle cx="126" cy="96" r="7" fill="#222"/>
<circle cx="96" cy="94" r="2.5" fill="#fff"/><circle cx="128" cy="94" r="2.5" fill="#fff"/>
<ellipse cx="110" cy="116" rx="11" ry="8" fill="#222"/>
<path d="{mouth}" stroke="#222" stroke-width="3" fill="none" stroke-linecap="round"/>
<path d="M110 134 q0 10 8 12" stroke="#e0607a" stroke-width="6" fill="none" stroke-linecap="round"/>
{extra if pose != 'car' else ''}
</svg>'''

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={'width': 240, 'height': 240}, device_scale_factor=2)
        for pose in ['wave', 'sit', 'car', 'cheer']:
            await pg.set_content(f'<html><body style="margin:0;background:#fff">{dog(pose)}</body></html>')
            await pg.screenshot(path=os.path.join(HERE, f'biscuit-{pose}.png'), omit_background=False)
            print('wrote', f'biscuit-{pose}.png')
        await b.close()

asyncio.run(main())
