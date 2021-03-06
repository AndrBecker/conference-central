#!/usr/bin/env python

"""
conference.py -- Udacity conference server-side Python App Engine API;
    uses Google Cloud Endpoints

$Id: conference.py,v 1.25 2014/05/24 23:42:19 wesc Exp wesc $

created by wesc on 2014 apr 21
"""

__author__ = 'wesc+api@google.com (Wesley Chun)'


from datetime import datetime

import endpoints
from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.api import memcache
from google.appengine.api import taskqueue
from google.appengine.ext import ndb

from models import ConflictException
from models import Profile
from models import ProfileMiniForm
from models import ProfileForm
from models import ProfileForms
from models import StringMessage
from models import BooleanMessage
from models import Conference
from models import ConferenceForm
from models import ConferenceForms
from models import ConferenceQueryForm
from models import ConferenceQueryForms
from models import TeeShirtSize

from models import SessionType
from models import Session
from models import SessionForm
from models import SessionForms
from models import Speaker
from models import SpeakerForm
from models import SpeakerForms

from settings import WEB_CLIENT_ID
from settings import ANDROID_CLIENT_ID
from settings import IOS_CLIENT_ID
from settings import ANDROID_AUDIENCE

from utils import getUserId

EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID
MEMCACHE_ANNOUNCEMENTS_KEY = "RECENT_ANNOUNCEMENTS"
MEMCACHE_FEATURED_SPEAKER_KEY = "FEATURED SPEAKER"
ANNOUNCEMENT_TPL = ('Last chance to attend! The following conferences '
                    'are nearly sold out: %s')
FEATURED_SPEAKER_TPL = ('Speaker %s features in the following sessions: %s')

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

DEFAULTS = {
    "city": "Default City",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": ["Default", "Topic"],
}

OPERATORS = {
            'EQ':   '=',
            'GT':   '>',
            'GTEQ': '>=',
            'LT':   '<',
            'LTEQ': '<=',
            'NE':   '!='
            }

FIELDS = {
            'CITY': 'city',
            'TOPIC': 'topics',
            'MONTH': 'month',
            'MAX_ATTENDEES': 'maxAttendees',
         }

CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

CONF_POST_REQUEST = endpoints.ResourceContainer(
    ConferenceForm,
    websafeConferenceKey=messages.StringField(1),
)

SESSION_POST_REQUEST = endpoints.ResourceContainer(
    SessionForm,
    websafeConferenceKey=messages.StringField(1),
)

SESSION_TYPE_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
    sessionType=messages.StringField(2),
)

SPEAKER_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeSpeakerKey=messages.StringField(1),
)

SESSION_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeSessionKey=messages.StringField(1),
)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -


@endpoints.api(name='conference', version='v1', audiences=[ANDROID_AUDIENCE],
               allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID,
                                   ANDROID_CLIENT_ID, IOS_CLIENT_ID],
               scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    """Conference API v0.1"""

# - - - Conference objects - - - - - - - - - - - - - - - - -

    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())
        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf

    def _createConferenceObject(self, request):
        """Create or update Conference object,
        returning ConferenceForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException(
                "Conference 'name' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name)
                for field in request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing
        # (both data model & outbound Message)
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])

        # convert dates from strings to Date objects;
        # set month based on start_date
        if data['startDate']:
            data['startDate'] = datetime.strptime(
                data['startDate'][:10], "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(
                data['endDate'][:10], "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
        # generate Profile Key based on user ID and Conference
        # ID based on Profile key get Conference key from ID
        p_key = ndb.Key(Profile, user_id)
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference, send email to organizer confirming
        # creation of Conference & return (modified) ConferenceForm
        Conference(**data).put()
        taskqueue.add(params={'email': user.email(),
                      'conferenceInfo': repr(request)},
                      url='/tasks/send_confirmation_email')
        return request


    @ndb.transactional()
    def _updateConferenceObject(self, request):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name)
                for field in request.all_fields()}

        # update existing conference
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        # check that conference exists
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' %
                request.websafeConferenceKey)

        # check that user is owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the conference.')

        # Not getting all the fields, so don't create a new object; just
        # copy relevant fields from ConferenceForm to Conference object
        for field in request.all_fields():
            data = getattr(request, field.name)
            # only copy fields where we get data
            if data not in (None, []):
                # special handling for dates (convert string to Date)
                if field.name in ('startDate', 'endDate'):
                    data = datetime.strptime(data, "%Y-%m-%d").date()
                    if field.name == 'startDate':
                        conf.month = data.month
                # write to Conference object
                setattr(conf, field.name, data)
        conf.put()
        prof = ndb.Key(Profile, user_id).get()
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))


    @endpoints.method(ConferenceForm, ConferenceForm, path='conference',
                      http_method='POST', name='createConference')
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)


    @endpoints.method(CONF_POST_REQUEST, ConferenceForm,
                      path='conference/{websafeConferenceKey}',
                      http_method='PUT', name='updateConference')
    def updateConference(self, request):
        """Update conference w/provided fields & return w/updated info."""
        return self._updateConferenceObject(request)


    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
                      path='conference/{websafeConferenceKey}',
                      http_method='GET', name='getConference')
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' %
                request.websafeConferenceKey)
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='getConferencesCreated',
                      http_method='POST', name='getConferencesCreated')
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # create ancestor query for all key matches for this user
        confs = Conference.query(ancestor=ndb.Key(Profile, user_id))
        prof = ndb.Key(Profile, user_id).get()
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(
                conf, getattr(prof, 'displayName')) for conf in confs]
        )


    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)

        # If exists, sort on inequality filter first
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(
                filtr["field"], filtr["operator"], filtr["value"])
            q = q.filter(formatted_query)
        return q


    def _formatFilters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {field.name: getattr(f, field.name)
                     for field in f.all_fields()}

            try:
                filtr["field"] = FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException(
                    "Filter contains invalid field or operator.")

            # Every operation except "=" is an inequality
            if filtr["operator"] != "=":
                # check if inequality operation has been used in
                # previous filters, disallow the filter if inequality was
                # performed on a different field before, track the field
                # on which the inequality operation is performed
                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException(
                        "Inequality filter is allowed on only one field.")
                else:
                    inequality_field = filtr["field"]

            formatted_filters.append(filtr)
        return (inequality_field, formatted_filters)


    @endpoints.method(ConferenceQueryForms, ConferenceForms,
                      path='queryConferences',
                      http_method='POST',
                      name='queryConferences')
    def queryConferences(self, request):
        """Query for conferences."""
        conferences = self._getQuery(request)

        # need to fetch organiser displayName from profiles
        # get all keys and use get_multi for speed
        organisers = [(ndb.Key(Profile, conf.organizerUserId))
                      for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return individual ConferenceForm object per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf,
                   names[conf.organizerUserId]) for conf in conferences]
        )


    @endpoints.method(CONF_GET_REQUEST, ProfileForms,
                      path='getConferenceAttendees',
                      http_method='GET',
                      name='getConferenceAttendees')
    def getConferenceAttendees(self, request):
        """Query for users attending the specified conference."""

        # find all profiles containing the conference key
        # in their conferences to attend
        profiles = Profile.query(
            Profile.conferenceKeysToAttend == request.websafeConferenceKey)

        # return profiles of conference attendees
        return ProfileForms(
            profiles=[self._copyProfileToForm(profile) for profile in profiles]
        )



# - - - Profile objects - - - - - - - - - - - - - - - - - - -

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name,
                            getattr(TeeShirtSize, getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf


    def _getProfileFromUser(self):
        """Return user Profile from datastore,
        creating new one if non-existent."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # get Profile from datastore
        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id)
        profile = p_key.get()
        # create new Profile if not there
        if not profile:
            profile = Profile(
                key=p_key,
                displayName=user.nickname(),
                mainEmail=user.email(),
                teeShirtSize=str(TeeShirtSize.NOT_SPECIFIED),
            )
            profile.put()

        return profile      # return Profile


    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # get user Profile
        prof = self._getProfileFromUser()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
                        # if field == 'teeShirtSize':
                        #    setattr(prof, field, str(val).upper())
                        # else:
                        #    setattr(prof, field, val)
                        prof.put()

        # return ProfileForm
        return self._copyProfileToForm(prof)


    @endpoints.method(message_types.VoidMessage, ProfileForm,
                      path='profile', http_method='GET', name='getProfile')
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()


    @endpoints.method(ProfileMiniForm, ProfileForm,
                      path='profile', http_method='POST', name='saveProfile')
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)



# - - - Announcements - - - - - - - - - - - - - - - - - - - -

    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """
        confs = Conference.query(ndb.AND(
            Conference.seatsAvailable <= 5,
            Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])

        if confs:
            # If there are almost sold out conferences,
            # format announcement and set it in memcache
            announcement = ANNOUNCEMENT_TPL % (
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            # If there are no sold out conferences,
            # delete the memcache announcements entry
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)

        return announcement


    @endpoints.method(message_types.VoidMessage, StringMessage,
                      path='conference/announcement/get',
                      http_method='GET', name='getAnnouncement')
    def getAnnouncement(self, request):
        """Return Announcement from memcache."""
        return StringMessage(
            data=memcache.get(MEMCACHE_ANNOUNCEMENTS_KEY) or "")



# - - - Registration - - - - - - - - - - - - - - - - - - - -

    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        # get user Profile
        prof = self._getProfileFromUser()

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)

        # register
        if reg:
            # check if user already registered otherwise add
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if wsck in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='conferences/attending',
                      http_method='GET', name='getConferencesToAttend')
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""
        # get user Profile
        prof = self._getProfileFromUser()
        conf_keys = [ndb.Key(urlsafe=wsck)
                     for wsck in prof.conferenceKeysToAttend]
        conferences = ndb.get_multi(conf_keys)

        # get organizers
        organisers = [ndb.Key(Profile, conf.organizerUserId)
                      for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(
                    conf, names[conf.organizerUserId])
                   for conf in conferences]
        )


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
                      path='conference/{websafeConferenceKey}',
                      http_method='POST', name='registerForConference')
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
                      path='conference/{websafeConferenceKey}',
                      http_method='DELETE', name='unregisterFromConference')
    def unregisterFromConference(self, request):
        """Unregister user for selected conference."""
        return self._conferenceRegistration(request, reg=False)


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='filterPlayground',
                      http_method='GET', name='filterPlayground')
    def filterPlayground(self, request):
        """Filter Playground"""
        q = Conference.query()
        # field = "city"
        # operator = "="
        # value = "London"
        # f = ndb.query.FilterNode(field, operator, value)
        # q = q.filter(f)
        q = q.filter(Conference.city == "London")
        q = q.filter(Conference.topics == "Medical Innovations")
        q = q.filter(Conference.month == 6)

        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, "") for conf in q]
        )


# - - - Sessions - - - - - - - - - - - - - - - - - - - -

    def _copySessionToForm(self, session):
        """Copy relevant fields from Session to SessionForm."""
        sf = SessionForm()
        for field in sf.all_fields():
            if hasattr(session, field.name):
                # convert Date/Time to date/time string; just copy others
                if field.name.endswith('Date') or field.name.endswith('Time'):
                    setattr(sf, field.name, str(getattr(session, field.name)))
                else:
                    setattr(sf, field.name, getattr(session, field.name))
            elif field.name == "websafeKey":
                setattr(sf, field.name, session.key.urlsafe())
        sf.check_initialized()
        return sf


    def _createSessionObject(self, request):
        """Create or session object, returning SessionForm/request."""

        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' %
                request.websafeConferenceKey)

        # get current user, must be organizer of conference
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if conf.organizerUserId != user_id:
            raise endpoints.UnauthorizedException(
                'User is not the organizer of the conference')

        # check required fields
        if not request.name:
            raise endpoints.BadRequestException(
                "Session 'name' field required")

        # copy SessionForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name)
                for field in request.all_fields()}
        del data['websafeKey']
        del data['websafeConferenceKey']

        # convert dates and times from strings to date and time objects
        if data['startDate']:
            data['startDate'] = datetime.strptime(
                data['startDate'][:10], "%Y-%m-%d").date()
        if data['startTime']:
            data['startTime'] = datetime.strptime(
                data['startTime'][:8], "%H:%M:%S").time()

        # generate Session Key with parent conference key
        s_id = Session.allocate_ids(size=1, parent=conf.key)[0]
        s_key = ndb.Key(Session, s_id, parent=conf.key)
        data['key'] = s_key

        # create Session & return SessionForm
        Session(**data).put()

        # task: if a speaker is referenced cache the speaker as
        # featured speaker provided the same speaker features
        # also in another session
        if request.speaker:
            taskqueue.add(
                params={'speakerKey': request.speaker},
                url='/tasks/store_featured_speaker')

        return self._copySessionToForm(s_key.get())


    @endpoints.method(SESSION_POST_REQUEST, SessionForm, path='session',
                      http_method='POST', name='createSession')
    def createSession(self, request):
        """Create new session."""
        return self._createSessionObject(request)


    @endpoints.method(SESSION_GET_REQUEST, BooleanMessage,
                      path='deleteSession',
                      http_method='DELETE', name='deleteSession')
    def deleteSession(self, request):
        """Delete session."""

        # find all profiles containing the session key in their wishlist
        profiles = Profile.query(
            Profile.sessionKeysWishlist == request.websafeSessionKey)

        # remove the session key in the wishlist and store in datastore
        for profile in profiles:
            profile.sessionKeysWishlist.remove(request.websafeSessionKey)
            profile.put()

        # delete session
        ndb.Key(urlsafe=request.websafeSessionKey).delete()

        return BooleanMessage(data=True)


    @endpoints.method(CONF_GET_REQUEST, SessionForms,
                      path='session/{websafeConferenceKey}',
                      http_method='GET', name='getConferenceSessions')
    def getConferenceSessions(self, request):
        """Return sessions of conference."""

        # create ancestor query for all session children of conference ancestor
        sessions = Session.query(ancestor=ndb.Key(
            urlsafe=request.websafeConferenceKey))

        # return set of SessionForm objects for the conference
        return SessionForms(
            sessions=[self._copySessionToForm(session) for session in sessions]
        )


    @endpoints.method(SESSION_TYPE_GET_REQUEST, SessionForms,
                      path='sessionsByType',
                      http_method='GET', name='getConferenceSessionsByType')
    def getConferenceSessionsByType(self, request):
        """Return conference sessions of specified type."""

        # create ancestor query for all session children of conference ancestor
        sessions = Session.query(ancestor=ndb.Key(
            urlsafe=request.websafeConferenceKey))

        # add filter for the specified session type to the query
        sessions = sessions.filter(Session.sessionType == request.sessionType)

        # return set of SessionForm objects
        return SessionForms(
            sessions=[self._copySessionToForm(session) for session in sessions]
        )


    @endpoints.method(SPEAKER_GET_REQUEST, SessionForms,
                      path='sessionsBySpeaker',
                      http_method='GET', name='getSessionsBySpeaker')
    def getSessionsBySpeaker(self, request):
        """Return conference sessions with specified speaker."""

        # retrieve all sessions in which speaker is referenced as their speaker
        sessions = Session.query().filter(
                        Session.speaker == request.websafeSpeakerKey)

        # return set of SessionForm objects for the retrieved sessions
        return SessionForms(
            sessions=[self._copySessionToForm(session) for session in sessions]
        )


    @endpoints.method(SESSION_GET_REQUEST, ProfileForms,
                      path='getSessionWishfulAttendees',
                      http_method='GET',
                      name='getSessionWishfulAttendees')
    def getSessionWishfulAttendees(self, request):
        """Query for users wishing to attend the specified session."""

        # find all profiles containing the session key in their wishlist
        profiles = Profile.query(Profile.sessionKeysWishlist ==
                                 request.websafeSessionKey)

        # return profiles
        return ProfileForms(
                profiles=[self._copyProfileToForm(profile)
                          for profile in profiles]
        )


# - - - User's session wishlist - - - - - - - - - - - - - - - - - - - -

    @endpoints.method(SESSION_GET_REQUEST, BooleanMessage,
                      path='addSessionToWishlist',
                      http_method='GET', name='addSessionToWishlist')
    def addSessionToWishlist(self, request):
        """Add session to user's wishlist."""

        retval = False

        # get session object from request; bail if not found
        session = ndb.Key(urlsafe=request.websafeSessionKey).get()
        if not session:
            raise endpoints.NotFoundException(
                'No session found with key: %s' % request.websafeSessionKey)

        # get user Profile
        profile = self._getProfileFromUser()

        if profile:
            # enter the sessions key to the user's withlist and
            # store in datastore
            if request.websafeSessionKey not in profile.sessionKeysWishlist:
                profile.sessionKeysWishlist.append(request.websafeSessionKey)
                profile.put()
            retval = True

        return BooleanMessage(data=retval)


    @endpoints.method(message_types.VoidMessage, SessionForms,
                      path='getSessionsInWishlist',
                      http_method='GET', name='getSessionsInWishlist')
    def getSessionsInWishlist(self, request):
        """Return conference sessions referenced in the user's wishlist."""

        # get Profile of current user
        profile = self._getProfileFromUser()

        # retrieve all sessions referenced in the user's wishlist
        session_keys = [ndb.Key(urlsafe=sKey)
                        for sKey in profile.sessionKeysWishlist]
        sessions = ndb.get_multi(session_keys)

        # return SessionForms response with all SessionForms of sessions
        # referenced in wishlist
        return SessionForms(
            sessions=[self._copySessionToForm(session) for session in sessions]
        )


    @endpoints.method(SESSION_GET_REQUEST, BooleanMessage,
                      path='deleteSessionInWishlist',
                      http_method='DELETE', name='deleteSessionInWishlist')
    def deleteSessionInWishlist(self, request):
        """Removes session from the user's wishlist."""

        # get current user's Profile
        profile = self._getProfileFromUser()

        # the session key has to be removed from the wishlist (if present)
        # independent of whether the session does or does not exist
        if request.websafeSessionKey in profile.sessionKeysWishlist:
            profile.sessionKeysWishlist.remove(request.websafeSessionKey)
            profile.put()

        # as an "add on" the existence of the referenced session is checked
        session = ndb.Key(urlsafe=request.websafeSessionKey).get()
        if not session:
            raise endpoints.NotFoundException(
                'No session found with key: %s' % request.websafeSessionKey)

        return BooleanMessage(data=True)



# - - - Speakers - - - - - - - - - - - - - - - - - - - -

    def _copySpeakerToForm(self, speaker):
        """Copy relevant fields from Speaker to SpeakerForm."""
        # for all fields in SpeakerForm copy the analogous parameter in the
        # Speaker object to the SpeakerForm
        sf = SpeakerForm()
        for field in sf.all_fields():
            if hasattr(speaker, field.name):
                setattr(sf, field.name, getattr(speaker, field.name))
            elif field.name == "websafeKey":
                setattr(sf, field.name, speaker.key.urlsafe())
        sf.check_initialized()
        return sf


    def _createSpeakerObject(self, request):
        """Create speaker object, returning speakerForm/request."""

        # check the required fields and throw exception is not set
        if not request.firstName:
            raise endpoints.BadRequestException(
                "Session 'firstName' field required")
        if not request.familyName:
            raise endpoints.BadRequestException(
                "Session 'familyName' field required")

        # copy SessionForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name)
                for field in request.all_fields()}
        del data['websafeKey']

        # generate an ndb key for the new Speaker entry
        s_id = Speaker.allocate_ids(size=1)[0]
        s_key = ndb.Key(Speaker, s_id)
        data['key'] = s_key

        # create Speaker & return SpeakerForm
        Speaker(**data).put()

        return request


    @endpoints.method(SpeakerForm, SpeakerForm, path='createSpeaker',
                      http_method='POST', name='createSpeaker')
    def createSpeaker(self, request):
        """Create new speaker."""
        return self._createSpeakerObject(request)


    @endpoints.method(SPEAKER_GET_REQUEST, BooleanMessage,
                      path='deleteSpeaker',
                      http_method='DELETE', name='deleteSpeaker')
    def deleteSpeaker(self, request):
        """Delete speaker."""

        # find all sessions containing the speaker key
        sessions = Session.query(Session.speaker == request.websafeSpeakerKey)

        # for each of these sessions reset the speakerKey property and store
        for session in sessions:
            session.speaker = ''
            session.put()

        # delete the session
        ndb.Key(urlsafe=request.websafeSpeakerKey).delete()

        return BooleanMessage(data=True)


    @endpoints.method(message_types.VoidMessage, SpeakerForms,
                      path='getSpeakers',
                      http_method='GET', name='getSpeakers')
    def getSpeakers(self, request):
        """Return all speakers."""
        # returns the speaker objects of all speakers stored in the datastore
        speakers = Speaker.query()
        return SpeakerForms(
            speakers=[self._copySpeakerToForm(speaker) for speaker in speakers]
        )


# - - - Featured Speaker - - - - - - - - - - - - - - - - - - - -

    @staticmethod
    def _cacheFeaturedSpeaker(speakerKey):
        """Set speaker as featured speaker in memcache
           if speaker features in at least 2 sessions.
        """
        # retrieve all sessions referencing the specified speaker
        sessions = Session.query(Session.speaker == speakerKey).fetch()

        if len(sessions) >= 2:
            # Speaker features in at least 2 sessions, so is stored in memcache
            # with key MEMCACHE_FEATURED_SPEAKER_KEY
            speaker = ndb.Key(urlsafe=speakerKey).get()
            speakerName = speaker.firstName + ' ' + speaker.familyName
            featuredSpeakerText = FEATURED_SPEAKER_TPL % \
                (speakerName, ', '.join(session.name for session in sessions))
            memcache.set(MEMCACHE_FEATURED_SPEAKER_KEY, featuredSpeakerText)
        return


    @endpoints.method(message_types.VoidMessage, StringMessage,
                      path='speaker/featured/get',
                      http_method='GET', name='getFeaturedSpeaker')
    def getFeaturedSpeaker(self, request):
        """Return the featured speaker from memcache if there is any."""
        return StringMessage(
            data=memcache.get(MEMCACHE_FEATURED_SPEAKER_KEY) or "")



# - - - Problem of multiple inequality filters in query - - - - - - - -

    # Example for two inequality filters in one query,
    # leads to a BadRequestError:
    # "BadRequestError: Only one inequality filter per query is supported.
    # Encountered both startTime and sessionType"
    @endpoints.method(message_types.VoidMessage, SessionForms,
                      path='filterInequalityNotOk',
                      http_method='GET', name='filterInequalityNotOk')
    def filterInequalityNotOk(self, request):
        """Execution leads to error as more than one inequality filter
        used in query"""
        q = Session.query()

        # first inequality filter in query over time
        startTime = datetime.strptime('19:00:00', "%H:%M:%S").time()
        q = q.filter(Session.startTime < startTime)

        # first inequality filter in query over session type
        q = q.filter(Session.sessionType != 'WORKSHOP')

        # retrieval returns a BadRequestError
        return SessionForms(
            sessions=[self._copySessionToForm(session) for session in q]
        )


    # Possible solution 1:
    # Usage of one inequality filter and  extensional equality filtering of
    # enumeration parameter with its value range
    # excluding the "inequality value".
    @endpoints.method(message_types.VoidMessage, SessionForms,
                      path='filterInequalityOk1',
                      http_method='GET', name='filterInequalityOk1')
    def filterInequalityOk1(self, request):
        """Combination of one inequality filter and
        extensional equality filtering of enumeration type"""
        q = Session.query()

        # apply inequality filter over time
        startTime = datetime.strptime('19:00:00', "%H:%M:%S").time()
        q = q.filter(Session.startTime < startTime)

        # apply equality filter on all values of sessionType value range
        # excepting value WORKSHOP
        q = q.filter(ndb.OR(
            Session.sessionType == 'NOT_SPECIFIED',
            Session.sessionType == 'LECTURE',
            Session.sessionType == 'TUTORIAL',
            Session.sessionType == 'KEYNOTE',
            Session.sessionType == 'OTHER'))

        return SessionForms(
            sessions=[self._copySessionToForm(session) for session in q]
        )


    # Possible solution 2:
    # Use of two query with one inequality filter each and intersection
    # of the result set keys.
    @endpoints.method(message_types.VoidMessage, SessionForms,
                      path='filterInequalityOk2',
                      http_method='GET', name='filterInequalityOk2')
    def filterInequalityOk2(self, request):
        """Intersection of keys resulting from 2 queries"""

        # first query with inequality filter over time
        startTime = datetime.strptime('19:00:00', "%H:%M:%S").time()
        q1 = Session.query(Session.startTime < startTime)
        session_keys1 = q1.fetch(keys_only=True)

        # second query with inequality filter over session type
        q2 = Session.query(Session.sessionType != 'WORKSHOP')
        session_keys2 = q2.fetch(keys_only=True)

        # retrieve result set of sessions objects by forming
        # the intersection of result key sets of the two queries
        sessions = ndb.get_multi(
            set(session_keys1).intersection(session_keys2))

        return SessionForms(
            sessions=[self._copySessionToForm(session) for session in sessions]
        )


    # Possible solution 3:
    # One inequality filter in query combined with filtering in Python.
    @endpoints.method(message_types.VoidMessage, SessionForms,
                      path='filterInequalityOk3',
                      http_method='GET', name='filterInequalityOk3')
    def filterInequalityOk3(self, request):
        """Combination of one inequality filter and
        usage of filtering in python"""

        # query with inequality filter over time
        startTime = datetime.strptime('19:00:00', "%H:%M:%S").time()
        q = Session.query()
        q = q.filter(Session.startTime < startTime)

        all_sessions = q.fetch()

        # check for inequality over session type in python loop
        sessions = []
        for session in all_sessions:
            if session.sessionType != 'WORKSHOP':
                sessions.append(session)

        return SessionForms(
            sessions=[self._copySessionToForm(session) for session in sessions]
        )


# register API
api = endpoints.api_server([ConferenceApi])
