#!/usr/bin/env python3
"""ProClean Quote API — Railway deployment"""
import os, json, re, math, io, base64, concurrent.futures
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pathlib import Path
from pydantic import BaseModel
import anthropic

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# Use the real public Claude model name
CLAUDE_MODEL = "claude-3-5-sonnet-20241022"

sessions: dict[str, list] = {}

SERVICE_ZIPS = {
  "98101","98102","98103","98104","98105","98106","98107","98108","98109",
  "98112","98115","98116","98117","98118","98119","98121","98122","98125",
  "98126","98133","98134","98136","98144","98146","98148","98155","98158",
  "98161","98164","98166","98168","98177","98178","98188","98195","98199",
  "98004","98005","98006","98007","98008","98009","98010","98011","98012",
  "98014","98019","98020","98021","98022","98024","98025","98027","98028",
  "98029","98033","98034","98036","98037","98038","98039","98040","98041",
  "98043","98045","98052","98053","98055","98056","98057","98058","98059",
  "98065","98072","98073","98074","98075","98077","98082","98083","98087",
  "98402","98403","98404","98405","98406","98407","98408","98409","98416",
  "98418","98421","98422","98424","98430","98433","98444","98446","98465",
  "98466","98467","98498","98499","98026"
}
KING_COUNTY_ZIPS = {
  "98101","98102","98103","98104","98105","98106","98107","98108","98109",
  "98112","98115","98116","98117","98118","98119","98121","98122","98125",
  "98126","98133","98134","98136","98144","98146","98148","98155","98158",
  "98161","98164","98166","98168","98177","98178","98188","98195","98199",
  "98004","98005","98006","98007","98008","98009","98010","98011","98014",
  "98019","98022","98024","98025","98027","98029","98033","98034","98038",
  "98039","98040","98041","98045","98052","98053","98055","98056","98057",
  "98058","98059","98065","98072","98073","98074","98075","98077","98092"
}
SNOHOMISH_COUNTY_ZIPS = {
  "98012","98020","98021","98026","98028","98036","98037","98043","98082",
  "98087","98201","98203","98204","98207","98208","98270","98271","98272",
  "98273","98274","98275","98290","98292","98296"
}

SYSTEM_PROMPT = """You are a professional quote assistant for ProClean, a residential exterior cleaning company in greater Seattle/Snohomish/King County. You help Cece (a ProClean sales rep) quickly generate accurate quotes while she's on the phone with customers.

## Your Role
When Cece tells you about a customer:
1. Use property data provided (from King County Assessor, Redfin, Zillow, Realtor.com, and satellite roof analysis)
2. Ask smart, SHORT follow-up questions only for what you don't already know
3. Recommend additional services naturally (upsell)
4. Calculate prices using the exact ResponsiBid pricing below
5. Output a clean ready-to-use quote

## Pricing

### Window Cleaning
- Small: Basic $95.94 | Basic+ $108.73 | In/Out $158.30 | Premium $193.48
- Medium: Basic $119.94 | Basic+ $135.93 | In/Out $197.90 | Premium $241.88
- Large: Basic $149.94 | Basic+ $169.93 | In/Out $247.40 | Premium $302.38
- XL: Basic $179.94 | Basic+ $203.93 | In/Out $296.90 | Premium $362.88
- XXL: Basic $239.94 | Basic+ $271.93 | In/Out $395.90 | Premium $483.88
- 2-story add: Small +$4.80 | Med +$6 | Lg +$7.50 | XL +$9 | XXL +$12
- Minimums: Basic $150 | Basic+ $155 | In/Out $210 | Premium $275

### House Washing
- Small $239.85 | Medium $299.85 | Large $374.85 | XL $449.85 | XXL $599.85
- 2-story: +5% for medium/large/XL/XXL | Minimum $125

### Roof Cleaning (Green Moss)
Soft Wash: Small $335.79 | Med $419.79 | Lg $524.79 | XL $629.79 | XXL $839.79
Soft Wash + Moss Removal: Small $575.64 | Med $719.64 | Lg $899.64 | XL $1079.64 | XXL $1439.64
Deluxe Plus: Small $399.75 | Med $499.75 | Lg $624.75 | XL $749.75 | XXL $999.75
- Roof pitch (use roofPitch from property data if available):
  - Low (1-6/12): no surcharge
  - Medium (7-9/12): +25% on all packages
  - Steep (10-12/12): Soft Wash +25%, Deluxe Plus +35%, Soft Wash+Moss +40%
  - If roofPitch not in data, estimate from stories: 1-story pre-1970=low, 1.5-story=medium, 2-story=medium, 3-story=steep
  - Always tell Cece what pitch you're using and why
- 2-story (Soft Wash only): Small +$63.96 | Med +$79.96 | Lg +$99.96 | XL +$119.96 | XXL +$159.96
- Minimums: Soft Wash $425 | Soft Wash+Moss $550 | Deluxe Plus $450
- Metal/Shake: ALWAYS say "Ask Chris — cannot be auto-quoted"

### Gutter Cleaning
Basic: Small $78.51 | Med $98.15 | Lg $122.70 | XL $147.25 | XXL $196.35 (min $225)
Deluxe: Small $83.95 | Med $104.95 | Lg $131.20 | XL $157.45 | XXL $209.95 (min $230)
Premium: Small $124.08 | Med $155.12 | Lg $193.92 | XL $232.72 | XXL $310.32 (min $235)
- Pitch surcharge: Low=none | Medium=Basic+15%,Deluxe+20%,Premium+25% | Steep=Basic+20%,Deluxe+25%,Premium+30%
- 3-story: +$100

### Deck Cleaning
- Soft Wash: $0.40/sqft (min $75) | Deep Clean: $0.65/sqft (min $100) | Deep Clean+Rails: $0.65/sqft (min $125)

### Driveway
Basic: 2-car $80 | 3-car $110 | 4-car $125 | 5-car $150 | 6-car $180
With Pre & Post: 2-car $229 | 3-car $329 | 4-car $499 | 5-car $549 | 6-car $599
- Mossy/pavers: +25% | Stained: +15%

### Patio/Walkway
Small $65 | Medium $95 | Large $125 | +10% moderately dirty | +25% really dirty/mossy

### Fence
6ft privacy wood $2.10/lf | 4-board vinyl $0.75/lf | 4ft wood picket $0.95/lf | 4ft vinyl picket $1.25/lf
Min $125 | Both sides: +$0.85/lf

### Solar: $5/panel | Skylights: $10/pane

## Size Guide
Small <1600 | Medium 1600-1999 | Large 2000-2499 | XL 2500-2999 | XXL 3000+

## Bundle Discount
- Do NOT apply automatically. Only apply if Cece says to ("apply the bundle", "give them the discount").
- You CAN mention it as an upsell option but never apply without Cece's go-ahead.
- When applied: set bundleApplied: true in quote JSON.

## Upselling
- Roof → "Adding gutters would get them the 20% bundle."
- House wash → "Adding driveway would qualify for the bundle."
- Deck → "Roof + deck together could get the bundle if you want to offer it."

## Quote Format
End your message with ONLY this JSON when ready:
```json
{
  "ready": true,
  "address": "...",
  "customerName": "...",
  "lineItems": [
    {"service": "Roof Cleaning", "package": "Soft Wash + Moss Removal", "price": 719.64, "description": "Medium home, medium pitch", "isAskChris": false}
  ],
  "subtotal": 719.64,
  "bundleApplied": false,
  "total": 719.64,
  "notes": [],
  "upsells": ["Adding gutter cleaning would qualify for 20% bundle"]
}
```

## Quote Process (explain to customers if asked)
- We do quotes remotely to keep costs down — we use photos and info found online.
- For window cleaning and gutter cleaning, we usually don't need extra pictures.
- Ask customers to send pictures for: moss removal / roof cleaning, pressure washing, gutter repairs, anything custom or unusual (weird window type, yard cleanup, etc.)
- Send a tech or Chris for on-site eval: multi-family/commercial properties, custom or complex jobs (pressure washing a dock, multiple gutter repairs, custom window types).
- Pricing is based on difficulty and volume of work (sq footage, roof steepness, driveway size, moss amount) — NOT zip code.

## Scheduling FAQ
- Scheduling is done by phone, text, or email based on geography + availability + customer timing.
- Once booked: system sends email reminder 3 days before, text reminder the day before.

## Service Area
Arlington, Beaux Arts Village, Bellevue, Bothell, Brier, Burien, Carnation, Clyde Hill, Duvall, Edmonds, Everett, Fall City, Hunts Point, Issaquah, Kenmore, Kirkland, Lake Forest Park, Lynnwood, Marysville, Medina, Mercer Island, Mill Creek, Mountlake Terrace, Mukilteo, Newcastle, Normandy Park, North Bend, Redmond, Renton, Sammamish, Seattle, Shoreline, Snohomish, Snoqualmie, Woodinville, Woodway, Yarrow Point (and nearby areas depending on job size).

## Service-Specific Questions

### Gutter Cleaning — always ask:
1. Roof material? (composition/asphalt/shingle = fine; wood shake or metal = check with Chris; unknown terms like "torchdown" or "PVC" = ask Chris)
2. Gutter covers? If mesh/screen that needs removal, note it and refer to Chris. Covers that just get blown off = no extra charge, mark "no" in Responsibid.
3. Roof anchors? (enables work on steeper roofs)

### Roof Cleaning — always ask:
- Moss/algae removal needed, or just leaves/debris? (debris = covered in Deluxe/Premium gutter packages)
- If moss/algae: ask customer to send pictures of affected areas
- Ask same questions as gutter cleaning above

### How we clean roofs (if customer asks):
- No-pressure approach: hand tools agitate moss at base of each shingle, blow off with backpack blower, clean gutters, apply preventative moss treatment at ridgeline.
- For roofs too steep to walk: soft wash (bleach solution kills but does NOT physically remove growth; includes gutter/downspout cleaning).
- We do NOT pressure wash roofs.

### Gutter Repairs:
- We do minor repairs: reattaching downspouts, hammering/screwing loose attachments, plugging small holes with gutter caulk. Need pictures if possible.
- We do NOT replace fascia boards or gutters, and we do NOT do roofing (not licensed).

### Window Cleaning — always ask:
- French panes? (true french panes = custom expensive homes or back doors; fake/decorative = not a concern)
- Storm windows? (usually older homes)

### Payment:
- Invoice emailed the business day after work is completed.
- Customers can pay by credit/debit card, Zelle, bank transfer, or check.

### Unknown questions:
- If you don't know the answer, say: "I'm new here — can I check with my manager and call you back?"

## On-Site Evaluation Flag 🟠
Some jobs CANNOT be quoted remotely — they need a tech or Chris to go out first.
Flag these immediately with: "🟠 ON-SITE EVALUATION NEEDED — send a tech or Chris before quoting."

Trigger this flag for:
- Commercial properties (any size)
- Multi-family properties (condos, apartments, duplexes, any building with multiple units)
- Gutter repairs — tell Cece: "📸 Photos needed — ask the customer to send pictures of the damaged gutters." Minor repairs can be quoted after seeing photos; complex ones flag for on-site.
- Moss removal requested but customer has NOT sent photos yet — tell Cece: "📸 Photos needed — ask the customer to send pictures of the affected roof areas before quoting."
- Pressure washing without photos — tell Cece: "📸 Photos needed — ask the customer to send pictures of the area to be pressure washed before quoting."
- Metal or shake roof (always "Ask Chris" + flag if it seems complex)
- Custom/unusual work (dock washing, unusual window types, yard cleanup, etc.) — tell Cece: "📸 Photos needed — ask the customer to send pictures so we can assess the job."
- Very large or unusually complex residential jobs
- Anything where you genuinely cannot calculate a price with confidence

When flagging, always tell Cece:
1. WHY it needs on-site (one short sentence)
2. WHO to send (tech for standard eval, Chris for complex/custom)
3. Whether to collect photos first before scheduling the visit

## Rules
- Keep messages SHORT — Cece is on the phone. Bullet points only.
- Never make up prices — use ONLY the tables above
- Metal/Shake: always "Ask Chris"
- When quote is ready, say "Here's your quote 👇"
- When on-site needed, do NOT produce a quote — flag it clearly instead
"""

class ChatRequest(BaseModel):
    message: str
    propertyData: dict | None = None

@app.get("/api/ping")
def ping():
    return {"ok": True}

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    html_path = Path(__file__).parent / "index.html"
    return html_path.read_text()

@app.post("/api/chat")
async def chat(req: Request, body: ChatRequest):
    visitor_id = req.headers.get("x-visitor-id", "default")
    if visitor_id not in sessions:
        sessions[visitor_id] = []
    session_msgs = sessions[visitor_id]
    system = SYSTEM_PROMPT
    if body.propertyData:
        system += f"\n\n## Current Property\n{json.dumps(body.propertyData, indent=2)}"
    session_msgs.append({"role": "user", "content": body.message})
    try:
        response = client.messages.create(
            model=CLAUDE_MODEL, max_tokens=1024, system=system, messages=session_msgs,
        )
        reply = response.content[0].text if response.content[0].type == "text" else ""
        session_msgs.append({"role": "assistant", "content": reply})
        quote_data = None
        m = re.search(r'```json\s*([\s\S]*?)\s*```', reply)
        if m:
            try: quote_data = json.loads(m.group(1))
            except: pass
        return {"message": reply, "quoteData": quote_data}
    except Exception as e:
        import traceback
        traceback.print_exc()
        # Remove the failed user message from session so it doesn't corrupt history
        if session_msgs and session_msgs[-1]["role"] == "user":
            session_msgs.pop()
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"Anthropic API error: {str(e)}")

@app.post("/api/session/clear")
async def clear_session(req: Request):
    visitor_id = req.headers.get("x-visitor-id", "default")
    sessions.pop(visitor_id, None)
    return {"ok": True}


# ── Helpers ──

def parse_addr(address):
    addr_upper = address.strip().upper()
    addr_no_zip = re.sub(r'\s*,?\s*\d{5}(-\d{4})?\s*$', '', addr_upper).strip()
    addr_no_state = re.sub(r'\s*,?\s*\bWA\b\s*$', '', addr_no_zip).strip()
    if ',' in addr_no_state:
        parts = [p.strip() for p in addr_no_state.split(',', 1)]
        return parts[0], parts[1]
    words = addr_no_state.split()
    SUFFIXES = {'ST','AVE','BLVD','DR','RD','LN','CT','PL','WAY','CIR','LOOP','HWY','NE','NW','SE','SW','N','S','E','W'}
    city_words, street_words = [], list(words)
    for i in range(len(words)-1, 0, -1):
        if words[i] in SUFFIXES:
            break
        city_words.insert(0, street_words.pop())
    return ' '.join(street_words), ' '.join(city_words)


def geocode_address(address):
    import requests as rl
    try:
        r = rl.get(
            "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress",
            params={"address": address, "benchmark": "2020", "format": "json"},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=6
        )
        matches = r.json().get("result", {}).get("addressMatches", [])
        if matches:
            c = matches[0]["coordinates"]
            return c["y"], c["x"]
    except:
        pass
    return None


def get_aerial_grid(lat, lon, zoom=20):
    import requests as rl
    try:
        from PIL import Image
    except ImportError:
        return None

    def to_tile(lat, lon, z):
        lat = max(-85.05112878, min(85.05112878, lat))
        sin_lat = math.sin(lat * math.pi / 180)
        px = int((lon + 180) / 360 * (256 << z))
        py = int((0.5 - math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi)) * (256 << z))
        return px >> 8, py >> 8

    def to_qk(tx, ty, z):
        qk = ""
        for i in range(z, 0, -1):
            d = 0
            mask = 1 << (i - 1)
            if tx & mask: d += 1
            if ty & mask: d += 2
            qk += str(d)
        return qk

    cx, cy = to_tile(lat, lon, zoom)
    grid = Image.new("RGB", (768, 768), (180, 180, 180))
    hdrs = {"User-Agent": "Mozilla/5.0"}
    fetched = 0
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            qk = to_qk(cx + dx, cy + dy, zoom)
            url = f"https://ecn.t0.tiles.virtualearth.net/tiles/a{qk}.jpeg?g=1"
            try:
                r = rl.get(url, headers=hdrs, timeout=5)
                if r.status_code == 200:
                    tile = Image.open(io.BytesIO(r.content))
                    grid.paste(tile, ((dx+1)*256, (dy+1)*256))
                    fetched += 1
            except:
                pass
    if fetched == 0:
        return None
    buf = io.BytesIO()
    grid.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def lookup_king_county(address, zip_code):
    import requests as rl
    from bs4 import BeautifulSoup
    prop = {}
    assessor_url = "https://blue.kingcounty.com/assessor/erealproperty/default.aspx"
    try:
        s = rl.Session()
        s.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "https://blue.kingcounty.com/assessor/erealproperty/default.aspx"})
        r0 = s.get("https://blue.kingcounty.com/Assessor/eRealProperty/default.aspx", timeout=8)
        soup0 = BeautifulSoup(r0.text, "html.parser")
        h0 = {inp["name"]: inp.get("value","") for inp in soup0.find_all("input",{"type":"hidden"}) if inp.get("name")}
        s.post("https://blue.kingcounty.com/Assessor/eRealProperty/default.aspx",
            data={**h0, "kingcounty_gov$cphContent$checkbox_acknowledge":"on","kingcounty_gov$cphContent$hf_accept":"1"}, timeout=8)
        r1 = s.get("https://blue.kingcounty.com/Assessor/eRealProperty/default.aspx", timeout=8)
        soup1 = BeautifulSoup(r1.text, "html.parser")
        h1 = {inp["name"]: inp.get("value","") for inp in soup1.find_all("input",{"type":"hidden"}) if inp.get("name")}
        street_full, city = parse_addr(address)
        r2 = s.post("https://blue.kingcounty.com/Assessor/eRealProperty/default.aspx",
            data={**h1,
                "kingcounty_gov$cphContent$txtAddress": street_full,
                "kingcounty_gov$cphContent$txtCity": city,
                "kingcounty_gov$cphContent$txtZip": zip_code,
                "kingcounty_gov$cphContent$btn_SearchAddress": "Search"},
            timeout=10, allow_redirects=True)
        if "Dashboard.aspx" in r2.url or "ParcelNbr" in r2.url:
            pm = re.search(r'ParcelNbr=(\d+)', r2.url)
            if pm:
                parcel = pm.group(1)
                prop["parcel"] = parcel
                assessor_url = f"https://blue.kingcounty.com/Assessor/eRealProperty/Detail.aspx?ParcelNbr={parcel}"
            soup2 = BeautifulSoup(r2.text, "html.parser")
            tbl = " | ".join(t.get_text(separator=" | ", strip=True) for t in soup2.find_all("table"))
            def ex(pat, t=tbl):
                m = re.search(pat, t, re.I)
                return m.group(1).strip() if m else None
            v = ex(r'Total Square Footage\s*\|\s*([\d,]+)')
            if v: prop["sqft"] = int(v.replace(",",""))
            v = ex(r'Year Built\s*\|\s*(\d{4})')
            if v: prop["yearBuilt"] = int(v)
            v = ex(r'Number Of Bedrooms\s*\|\s*(\d+)')
            if v: prop["bedrooms"] = v
            v = ex(r'Number Of Baths\s*\|\s*([\d.]+)')
            if v: prop["bathrooms"] = v
            v = ex(r'Lot Size\s*\|\s*([\d,]+)')
            if v: prop["lotSqft"] = int(v.replace(",",""))
            if pm:
                r3 = s.get(assessor_url, timeout=8)
                soup3 = BeautifulSoup(r3.text, "html.parser")
                tbl3 = " | ".join(t.get_text(separator=" | ", strip=True) for t in soup3.find_all("table"))
                v = ex(r'Stories\s*\|\s*([\d.]+)', tbl3)
                if v: prop["stories"] = float(v)
                v = ex(r'Deck Area SqFt\s*\|\s*(\d+)', tbl3)
                if v and int(v) > 0: prop["deckSqft"] = int(v)
                v = ex(r'Attached Garage\s*\|\s*(\d+)', tbl3)
                if v and int(v) > 0: prop["garageSqft"] = int(v)
    except:
        pass
    return prop, assessor_url


def lookup_kc_gis(address, zip_code):
    import requests as rl
    prop = {}
    try:
        m = re.match(r'^(\d+)\s+(.+?)(?:\s*,|\s+\w+\s*,?\s*WA)', address.strip(), re.I)
        if not m: return prop
        like = f"{m.group(1)} {m.group(2).strip().upper()[:20]}%"
        r = rl.get(
            "https://gismaps.kingcounty.gov/arcgis/rest/services/Property/KingCo_PropertyInfo/MapServer/2/query",
            params={"where": f"ADDR_FULL LIKE '{like}' AND ZIP5='{zip_code}'",
                    "outFields":"PIN,ADDR_FULL,ZIP5,LOTSQFT,PROPTYPE,PREUSE_DESC",
                    "f":"json","returnGeometry":"false","resultRecordCount":"1"},
            headers={"User-Agent":"Mozilla/5.0"}, timeout=6)
        feats = r.json().get("features",[])
        if feats:
            a = feats[0].get("attributes",{})
            if a.get("LOTSQFT"): prop["lotSqft"] = int(a["LOTSQFT"])
            prop["propType"] = a.get("PREUSE_DESC","").strip()
            prop["pin"] = a.get("PIN","")
    except:
        pass
    return prop


@app.post("/api/lookup")
async def lookup(body: dict):
    import urllib.parse
    import requests as rl

    address = body.get("address","")
    zip_match = re.search(r'\b(\d{5})\b', address)
    zip_code = zip_match.group(1) if zip_match else ""
    in_area = bool(zip_code and zip_code in SERVICE_ZIPS) if zip_code else True

    enc = urllib.parse.quote(address)
    maps_url      = f"https://www.google.com/maps/search/?api=1&query={enc}"
    satellite_url = f"https://www.google.com/maps/search/?api=1&query={enc}&layer=satellite"
    redfin_url    = f"https://www.redfin.com/search#location={enc}"
    addr_dash     = re.sub(r'[^a-zA-Z0-9]+', '-', address).strip('-')
    zillow_url    = f"https://www.zillow.com/homes/{enc}_rb/"
    realtor_url   = f"https://www.realtor.com/realestateandhomes-detail/{addr_dash}"

    prop = {}
    assessor_url_kc = "https://blue.kingcounty.com/assessor/erealproperty/default.aspx"

    def try_redfin():
        nonlocal redfin_url
        try:
            r = rl.get(
                f"https://www.redfin.com/stingray/do/location-autocomplete?location={enc}&count=1&v=2",
                headers={"User-Agent":"Mozilla/5.0","Accept":"application/json","X-Requested-With":"XMLHttpRequest","Referer":"https://www.redfin.com/"},
                timeout=6)
            clean = re.sub(r'^[{}&]+&&','',r.text).strip()
            data = json.loads(clean)
            hit = data.get("payload",{}).get("sections",[{}])[0].get("rows",[{}])[0]
            if hit.get("url"): redfin_url = "https://www.redfin.com" + hit["url"]
        except: pass

    def try_kc():
        nonlocal prop, assessor_url_kc
        if zip_code not in KING_COUNTY_ZIPS: return
        kc_prop, kc_url = lookup_king_county(address, zip_code)
        if kc_prop:
            prop.update({k:v for k,v in kc_prop.items() if v is not None})
            if "ParcelNbr" in kc_url: assessor_url_kc = kc_url
        if not prop:
            gis = lookup_kc_gis(address, zip_code)
            prop.update({k:v for k,v in gis.items() if v is not None})

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        concurrent.futures.wait([ex.submit(try_redfin), ex.submit(try_kc)], timeout=12)

    assessor_links = []
    if zip_code in KING_COUNTY_ZIPS:
        assessor_links.append({"label":"King Co. Assessor","url":assessor_url_kc,"county":"king"})
    if zip_code in SNOHOMISH_COUNTY_ZIPS:
        assessor_links.append({"label":"Snohomish Assessor","url":"https://snohomishcountywa.gov/5167/Assessor","county":"snohomish"})
    if not assessor_links:
        assessor_links = [
            {"label":"King Co. Assessor","url":assessor_url_kc,"county":"king"},
            {"label":"Snohomish Assessor","url":"https://snohomishcountywa.gov/5167/Assessor","county":"snohomish"}
        ]

    return {
        "inServiceArea": bool(in_area),
        "redfinUrl":     redfin_url,
        "zillowUrl":     zillow_url,
        "realtorUrl":    realtor_url,
        "mapsUrl":       maps_url,
        "satelliteUrl":  satellite_url,
        "assessorLinks": assessor_links,
        "propertyData":  prop if prop else None
    }


@app.post("/api/roof-vision")
async def roof_vision(body: dict):
    address = body.get("address","")
    lat = body.get("lat")
    lon = body.get("lon")

    if not lat or not lon:
        coords = geocode_address(address)
        if not coords:
            return {"error":"Could not geocode address","pitch":None,"roofType":None}
        lat, lon = coords

    img_bytes = get_aerial_grid(lat, lon, zoom=20) or get_aerial_grid(lat, lon, zoom=19)
    if not img_bytes:
        return {"error":"Could not fetch aerial image","pitch":None,"roofType":None}

    img_b64 = base64.b64encode(img_bytes).decode()
    prompt = f"""Satellite/aerial image of {address}. The subject property is near the CENTER.

Analyze the CENTER property's roof:
1. Pitch: LOW (1-6/12, flat/gentle), MEDIUM (7-9/12), or STEEP (10-12/12)
2. Roof type: composition, metal, flat/TPO, tile, shake/wood, or unknown
3. Confidence: high/medium/low

JSON only, no markdown:
{{"pitch":"low|medium|steep","roofType":"composition|metal|flat|tile|shake|unknown","confidence":"high|medium|low","reasoning":"one sentence"}}"""

    try:
        resp = client.messages.create(
            model=CLAUDE_MODEL, max_tokens=200,
            messages=[{"role":"user","content":[
                {"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":img_b64}},
                {"type":"text","text":prompt}
            ]}]
        )
        raw = re.sub(r'^```[a-z]*\n?|\n?```$','',resp.content[0].text.strip()).strip()
        result = json.loads(raw)
        result["imageAvailable"] = True
        return result
    except Exception as e:
        return {"error":str(e),"pitch":None,"roofType":None,"imageAvailable":True}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
