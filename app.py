import time
import ast
import urllib
import urllib2
import urlparse
import redis
import simplejson
import oauth2 as oauth 
from datetime import datetime,timedelta
from flask import Flask,redirect,render_template,url_for,request 
from flask.ext.sqlalchemy import SQLAlchemy

from settings import *

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
db = SQLAlchemy(app) 

def get_authurl(scope={'scope':'relationships'}):
    query = {'client_id':CLIENT_ID,'redirect_uri':REDIRECT_URL,'response_type':'code'}
    if scope:
        query.update(scope)
    params = urllib.urlencode(query)
    url = AUTH_URL + params
    
    return url

@app.route('/')
def index():
    url = get_authurl()
    print 'url',url
    return render_template("index.html",url=url)

@app.route('/callback/<code>')
def callback(code):
    code = code
    consumer = oauth.Consumer(key=CLIENT_ID,secret=CLIENT_SECRET)
    #make_url
    client = oauth.Client(consumer)
    params = {'grant_type':'authorization_code','redirect_uri':REDIRECT_URL,
                            'code':code,'client_id':CLIENT_ID,'client_secret':CLIENT_SECRET}
    response,content = client.request(TOKEN_URL,"POST",body=urllib.urlencode(params))
    if response['status'] != '200':
        raise Exception("Invalid response {} ".format(response['status']))
    
    result = ast.literal_eval(content)
    
    userid = result["user"]["id"]
    username = result["user"]["username"]
    access_token = result["access_token"]

    user = User.create(userid,username,access_token)
    
    return render_template("result.html",user=user)

class Insta(object):
    def __init__(self,user):
        self.user = user
        self.userid = user.userid
        self.access_token = user.access_token
        self.new_following = list()
        self.r = connection_redis()

    def get_user(self,userid=None):
        userid = userid or self.userid
        url = BASE_URL + '/users/{userid}?access_token={access_token}'.format(userid=userid,access_token=self.access_token)
        result = urllib2.urlopen(url)
        userdata = simplejson.load(result)["data"]
        return userdata

    def get_following(self):
        url = BASE_URL + '/users/{userid}/follows?access_token={access_token}'\
                                    .format(userid=self.userid,access_token=self.access_token)
        result = urllib2.urlopen(url)
        userdata = simplejson.load(result)["data"]
        print len(userdata)
        for id in map(lambda x:int(x["id"]),userdata):
            yield id


    def get_follower(self):
        url = BASE_URL + '/users/{userid}/followed-by?access_token={access_token}'.format(userid=self.userid,access_token=self.access_token)
        result = urllib2.urlopen(url)
        userdata = simplejson.load(result)["data"]
        yield map(lambda x:int(x["id"]),userdata)

    def get_relation(self,target_id):
        url = BASE_URL + '/users/{userid}/relationship?access_token={access_token}'\
                                    .format(userid=target_id,access_token=self.access_token)
        print url
        result = urllib2.urlopen(url)
        userdata = simplejson.load(result)["data"]
        return userdata

    def is_follwed(self,target_id):
        userdata = self.get_relation(target_id)
        print userdata[u"incoming_status"] == u"none"
        print userdata[u"incoming_status"]
        if userdata[u"incoming_status"] == u"none":
            return False
        return True

    def get_following_by_date(self,days=7):
        d = datetime.now() - timedelta(days=days)
        key = datetime.strftime(d,"%Y-%m-%d")
        return []
        ##TODO redis
        #return [int(i) for i in self.r.lrange(key,0,-1)]

    def following_expire(self,target_id,days=7):
        if target_id in self.get_following_by_date(days=7):
            return True
        return False

    def change_relation(self,target_id,action):
        url = BASE_URL + '/users/{userid}/relationship?access_token={access_token}'\
                             .format(userid=target_id,access_token=self.access_token)
        data = {"action":action}
        data = urllib.urlencode(data)
        result = self.request(url,data)

    def unfollow(self,target_id):
        self.change_relation(target_id,"unfollow")

    def start_following(self,target_id,least_follower=1000):
        user = self.get_user(target_id)
        print user
        print "following",user[u"username"],user[u"counts"]
        print user[u"counts"][u"followed_by"]
        if int(user[u"counts"][u"followed_by"]) < least_follower:
            print "too small"
            return
        self.change_relation(target_id,"follow")
        self.new_following.append(target_id)
        key = datetime.strftime(datetime.now(),"%Y-%m-%d")
        self.r.lpush(key,target_id)
        print "followed"

    def get_popular(self):
        pass

    def find_media_by_area(self,areas,distance=DISTANCE,num=5):
        #TODO get lat,lng from AREA
        areas_list = None
        for lat,lng in areas_list:
            url = BASE_URL + "/locations/search?lat={lat}&lng={lng}&distance={distance}&access_token={access_token}"\
                                                            .format(lat=lat,lng=lng,distance=distance,access_token=self.access_token)
            result = self.request(url)
            media_ids = map(lambda x:x["id"],result[0:num])
            return media_ids

    def find_media_by_keyword(self,keywords,num=20):
        userlist = list()
        for key in keywords:
            url = BASE_URL + "/tags/{key}/media/recent?access_token={access_token}"\
                                                            .format(key=key,access_token=self.access_token)
            print url
            result = self.request(url)
            for media_id,userid in map(lambda x:[x["id"],x["user"]["id"]],result[0:num]):
                #userid = self.get_user_by_media(media_id)
                userlist.append(userid)
        for user_id in set(userlist):
            yield user_id

    def get_user_by_media(self,media_id):
        #Wrap by media info?
        url = BASE_URL + "/media/{media_id}?access_token={access_token}"\
                                                        .format(media_id=media_id,access_token=self.access_token)
        print url
        result = self.request(url)
        return result["user"]["id"]

    def follow_by_keyword(self,keywords,least_follower):
        for user_id in self.find_media_by_keyword(keywords):
            self.start_following(user_id,least_follower)

    def save_redis_data(self):
        key = datetime.strftime(datetime.now(),"%Y-%m-%d")
        self.r.set(key,self.new_following)

    def request(self,url,data=None):
        result = urllib2.urlopen(url,data)
        userdata = simplejson.load(result)["data"]
        return userdata

class User(db.Model):
    id = db.Column(db.Integer,primary_key=True)
    userid = db.Column(db.Integer,unique=True)
    username = db.Column(db.String(255))
    access_token = db.Column(db.String(255),nullable=True)
    created_at = db.Column(db.DateTime)

    def __init__(self,userid,username=None,access_token=None):
        self.userid = userid
        self.username = username
        self.access_token = access_token
        self.created_at = datetime.now()

    def __repr__(self):
        return '<User {}>'.format(self.userid)

    @classmethod
    def get_by_userid(cls,userid):
        return cls.query.filter(cls.userid==userid).one()
    
    @classmethod
    def create(cls,userid,username,access_token):
        obj = cls(userid,username,access_token)
        db.session.add(obj)
        db.session.commit()

def connection_redis():
    pool = redis.ConnectionPool(host='localhost',port=6379)
    r = redis.Redis(connection_pool=pool)
    return r

def main():
    AREA = ["Tokyo"]
    KEYWORD = ["Sea","beach","london"]
    target_list = User.query.filter(User.access_token!=None)
    for user in target_list:
        insta_user = Insta(user)
        #follwers = insta_user.get_follwer()
        
        for i,following in enumerate(insta_user.get_following()):
            print i
            print "following",following,type(following)
            if not insta_user.is_follwed(following):
                print "not following",following
                if insta_user.following_expire(following,days=0):
                    print "unfollow",following
                    insta_user.unfollow(following)
            else:
                print following,"is_followed"
                
        #insta_user.follow_by_area(AREA,num=5)
        insta_user.follow_by_keyword(KEYWORD,least_follower=1000)

if __name__ == "__main__":
    app.run(debug=True)



    
