#!/usr/bin/env python

"""models.py

Udacity conference server-side Python App Engine data & ProtoRPC models

$Id: models.py,v 1.1 2014/05/24 22:01:10 wesc Exp $

created/forked from conferences.py by wesc on 2014 may 24

"""

__author__ = 'wesc+api@google.com (Wesley Chun)'

import httplib
import endpoints
from protorpc import messages
from google.appengine.ext import ndb

class ConflictException(endpoints.ServiceException):
    """ConflictException -- exception mapped to HTTP 409 response"""
    http_status = httplib.CONFLICT

class Profile(ndb.Model):
    """Profile -- User profile object"""
    displayName = ndb.StringProperty()
    mainEmail = ndb.StringProperty()
    teeShirtSize = ndb.StringProperty(default='NOT_SPECIFIED')
    conferenceKeysToAttend = ndb.StringProperty(repeated=True)
    sessionKeysWishlist = ndb.StringProperty(repeated=True)

class ProfileMiniForm(messages.Message):
    """ProfileMiniForm -- update Profile form message"""
    displayName = messages.StringField(1)
    teeShirtSize = messages.EnumField('TeeShirtSize', 2)

class ProfileForm(messages.Message):
    """ProfileForm -- Profile outbound form message"""
    displayName = messages.StringField(1)
    mainEmail = messages.StringField(2)
    teeShirtSize = messages.EnumField('TeeShirtSize', 3)
    conferenceKeysToAttend = messages.StringField(4, repeated=True)
    sessionKeysWishlist = messages.StringField(5, repeated=True)

class ProfileForms(messages.Message):
    """ProfileForms -- multiple Profile outbound form message"""
    profiles = messages.MessageField(ProfileForm, 1, repeated=True)


class StringMessage(messages.Message):
    """StringMessage-- outbound (single) string message"""
    data = messages.StringField(1, required=True)

class BooleanMessage(messages.Message):
    """BooleanMessage-- outbound Boolean value message"""
    data = messages.BooleanField(1)

class Conference(ndb.Model):
    """Conference -- Conference object"""
    name            = ndb.StringProperty(required=True)
    description     = ndb.StringProperty()
    organizerUserId = ndb.StringProperty()
    topics          = ndb.StringProperty(repeated=True)
    city            = ndb.StringProperty()
    startDate       = ndb.DateProperty()
    month           = ndb.IntegerProperty() # TODO: do we need for indexing like Java?
    endDate         = ndb.DateProperty()
    maxAttendees    = ndb.IntegerProperty()
    seatsAvailable  = ndb.IntegerProperty()

class ConferenceForm(messages.Message):
    """ConferenceForm -- Conference outbound form message"""
    name            = messages.StringField(1)
    description     = messages.StringField(2)
    organizerUserId = messages.StringField(3)
    topics          = messages.StringField(4, repeated=True)
    city            = messages.StringField(5)
    startDate       = messages.StringField(6) #DateTimeField()
    month           = messages.IntegerField(7)
    maxAttendees    = messages.IntegerField(8)
    seatsAvailable  = messages.IntegerField(9)
    endDate         = messages.StringField(10) #DateTimeField()
    websafeKey      = messages.StringField(11)
    organizerDisplayName = messages.StringField(12)

class ConferenceForms(messages.Message):
    """ConferenceForms -- multiple Conference outbound form message"""
    items = messages.MessageField(ConferenceForm, 1, repeated=True)

class TeeShirtSize(messages.Enum):
    """TeeShirtSize -- t-shirt size enumeration value"""
    NOT_SPECIFIED = 1
    XS_M = 2
    XS_W = 3
    S_M = 4
    S_W = 5
    M_M = 6
    M_W = 7
    L_M = 8
    L_W = 9
    XL_M = 10
    XL_W = 11
    XXL_M = 12
    XXL_W = 13
    XXXL_M = 14
    XXXL_W = 15

class ConferenceQueryForm(messages.Message):
    """ConferenceQueryForm -- Conference query inbound form message"""
    field = messages.StringField(1)
    operator = messages.StringField(2)
    value = messages.StringField(3)

class ConferenceQueryForms(messages.Message):
    """ConferenceQueryForms -- multiple ConferenceQueryForm inbound form message"""
    filters = messages.MessageField(ConferenceQueryForm, 1, repeated=True)




# ------  ADDITONS FOR SESSIONS AND SPEAKERS -------------------

class SessionType(messages.Enum):
    """SessionType -- session type enumeration value"""
    NOT_SPECIFIED = 1
    LECTURE = 2
    WORKSHOP = 3
    TUTORIAL = 4
    KEYNOTE = 5
    OTHER = 6


# Session

class Session(ndb.Model):
    """Session -- Session object"""
    name            = ndb.StringProperty(required=True)
    description     = ndb.StringProperty()
    topics          = ndb.StringProperty(repeated=True)
    highlights      = ndb.StringProperty(repeated=True)
    sessionType     = ndb.StringProperty(default='NOT_SPECIFIED')
    location        = ndb.StringProperty()
    startDate       = ndb.DateProperty()
    startTime       = ndb.TimeProperty()
    duration        = ndb.IntegerProperty() # unit is minutes
    speaker         = ndb.StringProperty()  # key of speaker


# SessionForm

class SessionForm(messages.Message):
    """SessionForm -- Session outbound form message"""
    name            = messages.StringField(1)
    description     = messages.StringField(2)
    topics          = messages.StringField(3, repeated=True)
    highlights      = messages.StringField(4, repeated=True)
    sessionType     = messages.StringField(5)
    location        = messages.StringField(6)
    startDate       = messages.StringField(7)
    startTime       = messages.StringField(8)
    duration        = messages.IntegerField(9)
    speaker         = messages.StringField(10)
    websafeKey      = messages.StringField(11)


# SessionForms

class SessionForms(messages.Message):
    """SessionForms -- multiple Session outbound form message"""
    sessions = messages.MessageField(SessionForm, 1, repeated=True)



# Speaker

class Speaker(ndb.Model):
    """Speaker -- Speaker object"""
    firstName       = ndb.StringProperty(required=True)
    familyName      = ndb.StringProperty(required=True)
    company         = ndb.StringProperty()
    institute       = ndb.StringProperty()
    expertise       = ndb.StringProperty(repeated=True)


# SpeakerForm

class SpeakerForm(messages.Message):
    """SpeakerForm -- Speaker form message"""
    firstName       = messages.StringField(1)
    familyName      = messages.StringField(2)
    company         = messages.StringField(3)
    institute       = messages.StringField(4)
    expertise       = messages.StringField(5, repeated=True)
    websafeKey      = messages.StringField(6)

# SpeakerForms

class SpeakerForms(messages.Message):
    """SpeakerForms -- multiple Speaker outbound form message"""
    speakers = messages.MessageField(SpeakerForm, 1, repeated=True)