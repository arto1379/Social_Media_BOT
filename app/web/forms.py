"""
Form definitions and validation.

Every form inherits from ``FlaskForm``, which brings CSRF protection with it -
that is why even the delete buttons submit a form rather than following a link.
Validation lives here so the views can assume clean input.
"""

from __future__ import annotations

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import (
    BooleanField,
    HiddenField,
    PasswordField,
    SelectField,
    SelectMultipleField,
    StringField,
    SubmitField,
    TextAreaField,
    widgets,
)
from wtforms.validators import (
    DataRequired,
    Email,
    EqualTo,
    Length,
    Optional,
    Regexp,
    ValidationError,
)

from app.models import LicenseType, VideoSource, VideoStatus
from app.security import permissions as perms

# Extensions accepted by the upload fields (mirrors config.ALLOWED_*).
VIDEO_EXTENSIONS = ["mp4", "mov", "mkv", "webm", "m4v", "avi"]
IMAGE_EXTENSIONS = ["jpg", "jpeg", "png"]

# Minimum password length. Long beats complex - see the note in CONFIGURE.md.
MIN_PASSWORD_LENGTH = 12


class CSRFOnlyForm(FlaskForm):
    """
    A form with nothing but a CSRF token.

    Used by action buttons (delete, retry, run job) so a state-changing request
    is always a POST carrying a valid token.
    """


class MultiCheckboxField(SelectMultipleField):
    """A list of checkboxes - used for granting permissions to a role."""

    widget = widgets.ListWidget(prefix_label=False)
    option_widget = widgets.CheckboxInput()


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
class LoginForm(FlaskForm):
    """The sign-in form."""

    username = StringField("Username", validators=[DataRequired(), Length(max=64)])
    password = PasswordField("Password", validators=[DataRequired()])
    remember = BooleanField("Stay signed in on this device")
    submit = SubmitField("Sign in")


class ChangePasswordForm(FlaskForm):
    """Password change for the signed-in user."""

    current_password = PasswordField("Current password", validators=[DataRequired()])
    new_password = PasswordField(
        "New password",
        validators=[
            DataRequired(),
            Length(
                min=MIN_PASSWORD_LENGTH,
                message=f"Use at least {MIN_PASSWORD_LENGTH} characters. "
                        f"A passphrase of a few words is both stronger and "
                        f"easier to remember than a short scrambled password.",
            ),
        ],
    )
    confirm_password = PasswordField(
        "Repeat new password",
        validators=[DataRequired(), EqualTo("new_password", "The passwords do not match.")],
    )
    submit = SubmitField("Change password")


# ---------------------------------------------------------------------------
# Videos
# ---------------------------------------------------------------------------
LICENSE_CHOICES = [(key, LicenseType.LABELS[key]) for key in LicenseType.ALL]
SOURCE_CHOICES = [
    (VideoSource.MANUAL, "Uploaded by hand"),
    (VideoSource.LIBRARY, "Server library folder"),
    (VideoSource.SPONSORED, "Sponsored / brand deal"),
    (VideoSource.ARCHIVE, "Own back-catalogue"),
]
PRIVACY_CHOICES = [("public", "Public"), ("unlisted", "Unlisted"), ("private", "Private")]
STATUS_CHOICES = [(status, status.title()) for status in VideoStatus.ALL]


class VideoMetadataMixin:
    """Fields shared by the upload form and the edit form."""

    title = StringField(
        "Title",
        validators=[DataRequired(), Length(max=100, message="YouTube allows 100 characters.")],
    )
    description = TextAreaField("Description", validators=[Optional(), Length(max=5000)])
    tags = StringField(
        "Tags",
        validators=[Optional(), Length(max=500)],
        description="Comma separated. YouTube counts all tags against a 500 character budget.",
    )
    category_id = SelectField("Category", choices=[], validators=[Optional()])
    privacy = SelectField("Privacy", choices=PRIVACY_CHOICES, default="public")
    language = StringField("Language", default="en", validators=[Optional(), Length(max=8)])
    made_for_kids = BooleanField("This video is made for kids")

    # --- Rights -------------------------------------------------------------
    license_type = SelectField(
        "Rights",
        choices=LICENSE_CHOICES,
        default=LicenseType.UNVERIFIED,
        description="Only owned or licensed material earns money. Royalty-free "
                    "clips are allowed but count as view-bait, not revenue.",
    )
    license_source = StringField(
        "Where it came from",
        validators=[Optional(), Length(max=255)],
        description="Studio, stock library, contributor - whoever supplied the footage.",
    )
    license_reference = StringField(
        "Licence or invoice reference",
        validators=[Optional(), Length(max=255)],
    )
    attribution = TextAreaField(
        "Attribution / credit line",
        validators=[Optional(), Length(max=1000)],
        description="Appended to the description when the setting is enabled. "
                    "Most royalty-free licences require it.",
    )
    source = SelectField("Source", choices=SOURCE_CHOICES, default=VideoSource.MANUAL)


class VideoUploadForm(VideoMetadataMixin, FlaskForm):
    """Add a new video by uploading a file through the website."""

    video_file = FileField(
        "Video file",
        validators=[
            FileRequired("Choose a video file to upload."),
            FileAllowed(VIDEO_EXTENSIONS, "Only video files are accepted."),
        ],
    )
    thumbnail_file = FileField(
        "Custom thumbnail (optional)",
        validators=[FileAllowed(IMAGE_EXTENSIONS, "Thumbnails must be JPG or PNG.")],
    )
    convert = BooleanField(
        "Convert to Shorts format if needed", default=True,
        description="Re-encodes landscape or over-long files into a vertical "
                    "1080x1920 clip with ffmpeg.",
    )
    trend_id = HiddenField()
    submit = SubmitField("Add video")


class VideoEditForm(VideoMetadataMixin, FlaskForm):
    """Edit an existing video's metadata."""

    status = SelectField("Status", choices=STATUS_CHOICES)
    thumbnail_file = FileField(
        "Replace thumbnail",
        validators=[FileAllowed(IMAGE_EXTENSIONS, "Thumbnails must be JPG or PNG.")],
    )
    submit = SubmitField("Save changes")


class RightsConfirmationForm(FlaskForm):
    """
    Explicit confirmation that the operator may publish this footage.

    Deliberately a separate action from editing metadata: approving publication
    is the moment somebody takes responsibility for the copyright position, and
    it is recorded in the audit log with their name on it.
    """

    confirm = BooleanField(
        "I confirm this material may be published on the connected channels",
        validators=[DataRequired("Tick the box to confirm.")],
    )
    submit = SubmitField("Confirm rights")


class QueueUploadForm(FlaskForm):
    """Queue a video for publishing on a chosen account."""

    account_id = SelectField("Publish to", coerce=int, validators=[DataRequired()])
    when = SelectField(
        "When",
        choices=[("now", "As soon as possible"), ("slot", "At the next publishing slot")],
        default="now",
    )
    submit = SubmitField("Queue upload")


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------
class AccountForm(FlaskForm):
    """Create the local record for a platform account before authorising it."""

    platform = SelectField("Platform", choices=[], validators=[DataRequired()])
    display_name = StringField(
        "Name", validators=[DataRequired(), Length(max=128)],
        description="A label for you - for example 'Main channel'.",
    )
    is_default = BooleanField("Use this account by default")
    submit = SubmitField("Save and connect")


# ---------------------------------------------------------------------------
# Users and roles
# ---------------------------------------------------------------------------
class UserForm(FlaskForm):
    """Create or edit a user. The password is optional when editing."""

    username = StringField(
        "Username",
        validators=[
            DataRequired(),
            Length(min=3, max=64),
            Regexp(
                r"^[A-Za-z0-9._-]+$",
                message="Use letters, digits, dots, underscores and hyphens only.",
            ),
        ],
    )
    full_name = StringField("Full name", validators=[Optional(), Length(max=128)])
    email = StringField("Email", validators=[Optional(), Email(), Length(max=255)])
    role_id = SelectField("Role", coerce=int, validators=[Optional()])
    extra_permissions = MultiCheckboxField("Additional permissions", choices=[])
    is_admin = BooleanField(
        "Administrator",
        description="Administrators have every permission, including user management.",
    )
    active = BooleanField("Account enabled", default=True)
    password = PasswordField(
        "Password",
        validators=[Optional(), Length(min=MIN_PASSWORD_LENGTH)],
        description=f"At least {MIN_PASSWORD_LENGTH} characters. Leave blank when "
                    f"editing to keep the current password.",
    )
    must_change_password = BooleanField(
        "Require a password change at next sign-in", default=True
    )
    submit = SubmitField("Save user")

    def __init__(self, *args, is_new: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self._is_new = is_new
        self.extra_permissions.choices = [
            (info.key, f"{info.label} - {info.description}") for info in perms.ALL
        ]

    def validate_password(self, field):
        """A new user must be given a password; an existing one may keep theirs."""
        if self._is_new and not field.data:
            raise ValidationError("Set a password for the new user.")


class RoleForm(FlaskForm):
    """Create or edit a role and the permissions it carries."""

    name = StringField("Role name", validators=[DataRequired(), Length(max=64)])
    description = StringField("Description", validators=[Optional(), Length(max=255)])
    permissions = MultiCheckboxField("Permissions", choices=[])
    submit = SubmitField("Save role")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.permissions.choices = [
            (info.key, f"{info.label} - {info.description}") for info in perms.ALL
        ]


class ResetPasswordForm(FlaskForm):
    """Administrator-driven password reset for another user."""

    password = PasswordField(
        "New password", validators=[DataRequired(), Length(min=MIN_PASSWORD_LENGTH)]
    )
    must_change_password = BooleanField(
        "Require a change at next sign-in", default=True
    )
    submit = SubmitField("Reset password")


# ---------------------------------------------------------------------------
# Trends
# ---------------------------------------------------------------------------
class TrendStatusForm(FlaskForm):
    """Move a trend through the pipeline."""

    status = SelectField(
        "Status",
        choices=[
            ("new", "New"),
            ("planned", "Planned"),
            ("used", "Used"),
            ("rejected", "Rejected"),
        ],
    )
    notes = TextAreaField("Notes", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Save")
