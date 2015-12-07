	Conference Central project for Udacity


--- Introduction ---

This application follows the specification of the Conference Central project
of the Udacity P4 project for the Udacity Fullstack Webdeveloper
Nanodegree. The application allows for the adminstration of conferences,
associated sessions, speakers and the participants' profiles.
It is implemented with the Google app engine technology in Python.

The code is as provided by Udacity in the respective github project,
but extended to the functionality involving sessions and speakers.



--- Links for Usage ---

The application installed in the Google cloud may be used in two ways:

1. With the App-Engine Api-Explorer only the backend functionality
can be used by executing the endpoint functions:

https://apis-explorer.appspot.com/apis-explorer/?base=https://goodoobie0.appspot.com/_ah/api#p/conference/v1/

Note: date parameter values must be formatted like '2015-11-12',
time parameter values like '20:00:00'.


2. With a web browser the frontend and parts of the backend
can be operated. Some functions of the backend cannot be used this way:

http://goodoobie0.appspot.com


The App-Engine application ID is 'goodoobie0'. A Google account
is required for actions involving write operations on datastore contents.

In the version of the software as checked in on github
the Webclient-Id has been removed in the files 'settings.py'
and 'static/js/app.js'.



--- Endpoints ---

The following endpoints were implemented as mandatory tasks
for the Udacticy P4 project:

- getConferenceSessions(websafeConferenceKey)
	-- Given a conference, return all sessions

- getConferenceSessionsByType(websafeConferenceKey, typeOfSession)
	-- Given a conference, return all sessions of a specified type
		(eg lecture, keynote, workshop)

- getSessionsBySpeaker(speaker)
	-- Given a speaker, return all sessions given
		by this particular speaker, across all conferences

- createSession(SessionForm, websafeConferenceKey)
	-- open only to the organizer of the conference

- addSessionToWishlist(SessionKey)
	-- adds the session to the user's list of sessions
		they are interested in attending

- getSessionsInWishlist()
	-- query for all the sessions in a conference that the user
		is interested in

- deleteSessionInWishlist(SessionKey)
	-- removes the session from the user’s list of sessions
		they are interested in attending

- getFeaturedSpeaker()
	-- returns a speaker from memcache that features
		in at least two sessions (if there is such a speaker)



The following additional endpoints were also implemented:

- getConferenceAttendees(websafeConferenceKey)
	-- returns all the profiles of the attendess of a conference


- getSessionWishfulAttendees(websafeSessionKey)
	-- returns the profiles of all users
		having the specified session in their wishlist

- deleteSession(websafeSessionKey)
	-- deletes the session and all references to it in users' wishlists

- createSpeaker(Speaker)
	-- creates a speaker

- deleteSpeaker(websafeSpeakerKey)
	-- deletes the speaker with all references in sessions

- getSpeakers()
	-- returns all speakers




--- Design approach for realisation of Sessions and Speakers ---

The Session ndb model represents a session in the datastore.
As session are associated with conferences in an n:1 relation
Session objects are created with a conference as ancestor.
This allows for queries by kind filtered by ancestor to get
all sessions of a conference.

Session-related reqests/responses are represented in SessionForm-objects
derived from the messages.Message class. As to represent a list of
Sessions in requests/responses a SessionForms class is defined.

The design of the speaker follows a similar scheme by defining
a Speaker ndb model and SpeakerForm/SpeakerForms message classes.
Speaker objects are detached in the sense that they are not created
with an ancestor. It would not make sense to create a speaker with
a session as ancestor as a speaker might appear in several sessions
of several conferences. A speaker is referenced with a
string property ('speaker') in the Session object (has-a relation).
This property is not required, so Sessions may be generated without
specifying a speaker (i.e. it may be unclear initially who might
feature as speaker for a session).

One issue is the current design of the startDate and startTime in the
Session model. Both properties might alternatively be joined to
a DateTimeProperty. I felt that queries might be simpler when
they are kept as distinct properties (I might be wrong on this point).
Interestingly values of these properties are displayed
in the Api-Explorer in a DateTime format although defined as DateProperty
and TimeProperty respectively:

startDate: 2015-11-12 00:00:00
startTime: 1970-01-01 20:00:00




--- Discussion of the issue of two inequality filters in one query ---

The problem with a query like "all non-workshop sessions before 7 pm"
is that it contains two inequality filter constraints.
Ndb queries can only contain one inequality filter,
otherwise a BadRequestError is created:


The implementation in endpoint "filterInequalityNotOk"
contains the query with the two inequality filters and creates the error:

"BadRequestError: Only one inequality filter per query is supported.
Encountered both startTime and sessionType."


Possible solutions that came to my mind are implemented in the following
endpoints (note: all implementations run on the complete set of Sessions,
neglecting their association with their respective conference):

- filterInequalityOk1:

	The implemented query uses only the inequality filter for the start time
	and checks in an OR-clause all possible values of SessionType excluding
	the "WORKSHOP"-value. This solution is possible because the
	SessionType property has a finite and small value range.

- filterInequalityOk2:

	This solution uses a separate query for each of the inequality filters 
	returning session keys as result sets. Then the intersection of the
	key sets is formed as the keys of all those sessions fulfilling both
	inequality criteria. 

- filterInequalityOk3:

    	This solution uses one query with one inequality filter combined with
	filtering in Python. Maybe not very elegant.


There may be another solution by using the MapReduce library ostensibly
allowing for multiple filters but I have not looked into this library yet.


