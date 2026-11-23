"""
Google Jobs CSS/ARIA selectors — for the Google Jobs search results page.
Google Jobs is used only for job discovery (not application).
"""

# ── Search ───────────────────────────────────────────────────
GOOGLE_JOBS_URL = "https://www.google.com/search"

# Job listing container within Google Jobs widget
JOB_LIST_CONTAINER = '#search .iFjolb, [jscontroller="AxHcid"]'
JOB_CARD = '.PwjeAc, [data-ved] .BjJfJf'
JOB_CARD_TITLE = '.BjJfJf, .sH3zle h3'
JOB_CARD_COMPANY = '.vNEEBe, .nJlDiv'
JOB_CARD_LOCATION = '.Qk80Jf, .vNEEBe + div'

# ── Job Detail Panel ─────────────────────────────────────────
DETAIL_PANEL = '.pE8vnd, [jscontroller="UdFUfe"]'
DETAIL_TITLE = '.KLsYvd h2, .sH3zle h2'
DETAIL_COMPANY = '.nJlDiv, .vNEEBe'
DETAIL_LOCATION = '.sMzDkb, .Qk80Jf'
DETAIL_DESCRIPTION = '.HBvzbc, .YgLbBe'

# ── Apply Links (we extract these to identify LinkedIn/Internshala links) ───
APPLY_LINK = '.pMhGee a, .B8oxKe a'
APPLY_LINK_TEXT = '.pMhGee a span, .B8oxKe a'

# ── Pagination / Load More ───────────────────────────────────
LOAD_MORE = '.Sf38ec, [aria-label="More jobs"]'
NEXT_PAGE = '.eFjMJe a[aria-label="Next"], .pQnx9e'
