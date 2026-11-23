"""
Internshala CSS/ARIA selectors — isolated here for easy maintenance.
"""

# ── Login / Session ──────────────────────────────────────────
LOGGED_IN_INDICATORS = [
    '.profile_container',
    '#student_dashboard',
    '.nav-login-name',
    '.user_name',
]

CHECKPOINT_INDICATORS = [
    '.captcha_container',
]

# ── Search ───────────────────────────────────────────────────
INTERNSHIP_SEARCH_URL = "https://internshala.com/internships/"
JOB_SEARCH_URL = "https://internshala.com/jobs/"

LISTING_CARD = '.individual_internship, .individual_job'
LISTING_TITLE = '.company_and_premium h3 a, .job-title-href'
LISTING_COMPANY = '.company_name a, .company-name'
LISTING_LOCATION = '#location_names a, .locations a'
LISTING_STIPEND = '.stipend, .salary'
LISTING_LINK = '.company_and_premium h3 a, .job-title-href'
LISTING_POSTED = '.status-info span, .posted-info'
LISTING_ID_ATTR = 'data-internship_id'

# ── Job Detail Page ──────────────────────────────────────────
DETAIL_TITLE = '.profile_header_details .heading_4_5 span'
DETAIL_COMPANY = '.profile_header_details .company_name a'
DETAIL_LOCATION = '#location_names a'
DETAIL_DESCRIPTION = '.internship_details .text-container'
DETAIL_STIPEND = '.stipend_container .stipend'

# ── Application ──────────────────────────────────────────────
APPLY_BUTTON = '#continue_button, .apply_button, button.btn-primary[type="submit"]'
COVER_LETTER_TEXTAREA = '#cover_letter, textarea[name="cover_letter"]'
CUSTOM_QUESTION = '.assessment_question'
CUSTOM_QUESTION_TEXT = '.assessment_question label'
CUSTOM_QUESTION_INPUT = '.assessment_question textarea, .assessment_question input'
SUBMIT_BUTTON = '#submit, button[type="submit"].submit_button_text'

# ── Pagination ───────────────────────────────────────────────
PAGINATION_NEXT = '#navigation a[rel="next"], .pagination a.next'
PAGINATION_CONTAINER = '#navigation, .pagination'
