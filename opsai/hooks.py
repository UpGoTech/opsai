app_name = "opsai"
app_title = "OpsAi"
app_publisher = "OpsAi"
app_description = "Per-user AI settings vault for OpsAi"
app_email = "opsai@example.com"
app_license = "MIT"
app_icon = "octicon octicon-comment-discussion"
app_color = "#3B87F7"
app_logo_url = "/assets/opsai/images/opsai-logo.svg"
# Desk workspace (not /opsai full-page chat). Non-desk app_home makes the dock
# treat OpsAi as an external app and window.location to /opsai.
app_home = "/desk/opsai"

required_apps = []

# Apps screen tile (Frappe v16+ desk) → OpsAi workspace inside Desk
add_to_apps_screen = [
	{
		"name": app_name,
		"logo": app_logo_url,
		"title": app_title,
		"route": app_home,
		"has_permission": "opsai.check_app_permission",
	}
]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# Dock icon + right-side OpsAi panel (Flow fork: opsai.chat island).
# CSS hides the sidebar OpsAi row when the pinned dock already shows the icon.
# ?v= busts browser cache when dock/launcher behavior changes (plain public JS).
app_include_css = [
	"/assets/opsai/css/opsai_dock.css?v=7",
	"/assets/opsai/css/opsai_users_form.css?v=3",
]
app_include_js = [
	"/assets/opsai/js/opsai_dock.js?v=7",
	"/assets/opsai/js/opsai_launcher.js?v=7",
]

# include js, css files in header of web template
# web_include_css = "/assets/opsai/css/opsai.css"
# web_include_js = "/assets/opsai/js/opsai.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "opsai/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Home Pages
# ----------

# Full-page OpsAi chat (Flow-style /opsai SPA)
website_route_rules = [
	{"from_route": "/opsai/<path:app_path>", "to_route": "opsai"},
]

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "opsai.utils.jinja_methods",
# 	"filters": "opsai.utils.jinja_filters"
# }

# Installation
# ------------

after_install = "opsai.install.after_install"
after_migrate = ["opsai.permissions.ensure_opsai_role"]

# Uninstallation
# ------------

before_uninstall = "opsai.uninstall.before_uninstall"

# Boot: has_opsai_access for dock/sidebar utility visibility
extend_bootinfo = "opsai.boot.extend_bootinfo"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "opsai.utils.before_app_install"
# after_app_install = "opsai.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "opsai.utils.before_app_uninstall"
# after_app_uninstall = "opsai.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "opsai.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

permission_query_conditions = {
	"OpsAi Users": "opsai.opsai.doctype.opsai_users.opsai_users.get_permission_query_conditions",
}

has_permission = {
	"OpsAi Users": "opsai.opsai.doctype.opsai_users.opsai_users.has_permission",
}

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"opsai.tasks.all"
# 	],
# 	"daily": [
# 		"opsai.tasks.daily"
# 	],
# 	"hourly": [
# 		"opsai.tasks.hourly"
# 	],
# 	"weekly": [
# 		"opsai.tasks.weekly"
# 	],
# 	"monthly": [
# 		"opsai.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "opsai.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "opsai.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "opsai.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["opsai.utils.before_request"]
# after_request = ["opsai.utils.after_request"]

# Job Events
# ----------
# before_job = ["opsai.utils.before_job"]
# after_job = ["opsai.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"opsai.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }
