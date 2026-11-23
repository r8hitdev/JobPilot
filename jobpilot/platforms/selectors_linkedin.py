"""
LinkedIn CSS/ARIA selectors — isolated here so they're easy to update when LinkedIn changes its DOM.
Prefers role-based and text-based locators where possible.
"""

# ── Login / Session ──────────────────────────────────────────
LOGGED_IN_INDICATORS = [
    'div.feed-identity-module',
    '[data-control-name="identity_welcome_message"]',
    'img.global-nav__me-photo',
    '.global-nav__me',
]

CHECKPOINT_INDICATORS = [
    '[data-test="challenge"]',
    '#captcha-internal',
    '.checkpoint-challenge',
]

# ── Job Search ───────────────────────────────────────────────
JOBS_SEARCH_URL = "https://www.linkedin.com/jobs/search/"

JOB_CARDS = 'ul.scaffold-layout__list-container li.jobs-search-results__list-item'
JOB_CARD_TITLE = 'a.job-card-list__title'
JOB_CARD_COMPANY = 'span.job-card-container__primary-description'
JOB_CARD_LOCATION = 'li.job-card-container__metadata-item'
JOB_CARD_LINK = 'a.job-card-list__title'

# ── Job Detail Panel ─────────────────────────────────────────
JOB_DETAIL_TITLE = 'h1.job-details-jobs-unified-top-card__job-title'
JOB_DETAIL_COMPANY = '.job-details-jobs-unified-top-card__company-name'
JOB_DETAIL_LOCATION = '.job-details-jobs-unified-top-card__bullet'
JOB_DETAIL_DESCRIPTION = '.jobs-description-content__text'
JOB_DETAIL_ID_ATTR = 'data-job-id'

# ── Easy Apply Modal ─────────────────────────────────────────
EASY_APPLY_BUTTON = 'button.jobs-apply-button'
EASY_APPLY_MODAL = '.jobs-easy-apply-modal'
EASY_APPLY_NEXT = 'button[aria-label="Continue to next step"]'
EASY_APPLY_REVIEW = 'button[aria-label="Review your application"]'
EASY_APPLY_SUBMIT = 'button[aria-label="Submit application"]'
EASY_APPLY_CLOSE = 'button[aria-label="Dismiss"]'
EASY_APPLY_DISCARD = 'button[data-control-name="discard_application_confirm_btn"]'

# Form fields
FORM_TEXT_INPUT = '.jobs-easy-apply-form-section__grouping input[type="text"]'
FORM_SELECT = '.jobs-easy-apply-form-section__grouping select'
FORM_TEXTAREA = '.jobs-easy-apply-form-section__grouping textarea'
FORM_RADIO = '.jobs-easy-apply-form-section__grouping input[type="radio"]'
FORM_CHECKBOX = '.jobs-easy-apply-form-section__grouping input[type="checkbox"]'
FORM_FILE_UPLOAD = 'input[type="file"]'
FORM_FIELD_LABEL = '.jobs-easy-apply-form-section__grouping label'
FORM_REQUIRED = '[required]'

# ── Pagination ───────────────────────────────────────────────
PAGINATION_NEXT = 'button[aria-label="View next page"]'
PAGINATION_PAGES = 'li[data-test-pagination-page-btn]'

# ── External Apply ───────────────────────────────────────────
EXTERNAL_APPLY_BUTTON = 'button.jobs-apply-button--external'
