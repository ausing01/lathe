# region.py - stock boundary by clicking

Replaces the open-edge toggle idea entirely. The boundary walk IS the open side.

## One click does everything
- the profile/extension intersection nearest the click becomes the walk's start
- direction is whichever way round the loop reaches the click first
- the walk runs from there and STOPS at the next intersection it meets

If that is not far enough, click again and it continues from where it stopped -
the same extend-by-clicking behaviour the profile chain has. `clear walk` starts
over.

## Trimming
Elements are cut at the intersection points, so the first and last of a segment
are usually partial. On part 1 with a 6.0 stock, clicking up the face gives the
full 3.0 face plus the OD trimmed from 4.5 to 4.2, stopping at the end
extension. Pieces are tagged `origin="stock"` and keep the source_id of the
stock element they came from.

## State is the click history
The client keeps the clicks and the server replays them, so the walk accumulates
and is reproducible. Two clicks on part 1 give a five-element boundary running
face, OD, back corner, back face and centreline.

## Extensions past the stock
The crossing point is used, as asked. An extension that never reaches the stock
gives no region and is reported - roughing would have nothing to work in anyway.

Note a solid bar always touches a centreline-reaching profile, since its bottom
edge is the centreline. Testing the miss case needs a tube whose bore clears the
part.

## API
    stock_click(stock, extended, click_pt, chain_end_s=None)
      -> (elements, end_s, notes)

`profile_stock_intersections(extended, stock)` lists the stop points as loop
distances.

## Same flow for DXF stock
Closed-loop DXF stock uses exactly this: click the side you want. There is no
separate open-edge marking anywhere now.
