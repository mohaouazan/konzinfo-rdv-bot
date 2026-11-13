"""Selecteurs et textes de l'interface anglaise (?lng=en), verifies le 2026-11-13 sur la V2.1.23.

Tout changement de structure du site se corrige ici.
"""

# ---- chargement / sante
TXT_WELCOME = r"I wish to book an appointment"
BLAZOR_ERROR = "#blazor-error-ui"
BLOCK_UI = ".blockUI.blockOverlay, .blockUI.blockMsg"
PROGRESS_NAV = ".appointment-progress"
TXT_IP_BANNED = ("letiltásra került", "IP address has been blocked", "Access Denied")

# ---- etape 1 : donnees de reservation
BTN_SELECT_LOCATION = "Select location"
MODAL_CONSULATE = "#modal2"                       # « Please select a Consulate »
MODAL_SEARCH = "input[placeholder='Search']"
LABEL_IN_MODAL = "label.form-check-label"         # radios (consulats) / checkboxes (demandes)
TXT_SELECTED_CONSULATE = "Selected Consulate"
BTN_SELECT_APPLICATION = "Select type of application"
MODAL_CASES = "#modalCases"                       # « Applications »
BTN_SAVE = "Save"
TXT_SELECTED_CASES = "Selected case types"
INPUT_NAME = "#label4"
INPUT_APPLICANTS = "#label6"
INPUT_PHONE = "#label9"                           # placeholder « e.g. +3612345678 »
INPUT_EMAIL = "#label10"
LABEL_EMAIL2 = "Re-enter the email address"       # id aleatoire -> par libelle
INPUT_PASSPORT = "#label1000"                     # champ dynamique (visa)
DUET_BIRTH = "#birthDateComponent"                # <duet-date-picker identifier="birthDate">
DUET_INPUT = "input.duet-date__input"
DATE_FORMAT = "%d/%m/%Y"                          # placeholder « e.g. 30/01/1990 »
CHK_ACK = "#slabel13"                             # « I have read and acknowledged ... »
CHK_CONSENT = "#label13"                          # « I give my consent ... »
BTN_SELECT_DATE = r"Select date"
TXT_NO_SLOTS = "there are currently no appointments available"
BTN_OK = r"^OK"
VALIDATION_MSGS = ".text-danger, .invalid-feedback, .validation-message, .alert-danger"

# ---- etape 2 : choix de la date / du creneau
DUET_PERIOD = "#idoszakComponent"                 # <duet-date-picker identifier="idoszak"> (« Time period »)
DUET_TOGGLE = "button.duet-date__toggle"
DUET_DIALOG_ACTIVE = ".duet-date__dialog.is-active"
DUET_MONTH = "select.duet-date__select--month"    # value 0..11
DUET_YEAR = "select.duet-date__select--year"
DUET_NEXT = "button.duet-date__next"
DUET_PREV = "button.duet-date__prev"
DUET_DAY = "button.duet-date__day"
DUET_DAY_ENABLED = "button.duet-date__day:not([disabled]):not(.is-outside):not(.is-disabled)"
SLOT_BOX = "div.box"
SLOT_FREE = "div.box.free"
SLOT_SELECTED = "div.box.selected, div.box.selected2"
PAGINATION_NEXT = ".pagination .page-item:not(.disabled) .page-link:has-text('»')"
BTN_CONTINUE = r"Continue to validation"
BTN_BACK_DATA = r"Back to booking data"

# ---- etapes 3 / 4
BTN_COMPLETE = r"Complete booking"
TXT_CONFIRMED = "registered your booking"
HCAPTCHA = ".h-captcha, iframe[src*='hcaptcha.com']"

# ---- appels API (points de synchronisation ; corps binaire, non decode)
API_SERVICES = "GetCustomerServices"
API_CASES = "GetCustomerServiceCaseTypes"
API_CHECK = "CheckAvailableBookingTimes"
API_TIMES = "GetAvailableBookingTimes"
API_BOOKING_TIME = "BookingTime"
API_FINALIZE = "FinalizeBookingData"
