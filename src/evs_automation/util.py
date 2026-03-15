import datetime as _datetime

# Convert a scripting "date" value to a datetime.datetime
def evsdate_to_datetime(s):
    try:
        return _datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%f")
    except:
        return _datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")

# Convert a datetime.datetime to a scripting "date" value 
def datetime_to_evsdate(d):	
    return d.strftime("%Y-%m-%dT%H:%M:%S.%f")

# Convert a datetime.datetime into an excel compatible date number
def datetime_to_excel(d):
    temp = _datetime.datetime(1899, 12, 30)
    delta = d - temp
    return float(delta.days) + (float(delta.seconds) / 86400)

# Convert a scripting "date" into an excel compatible date number    
def evsdate_to_excel(d):
    date = evsdate_to_datetime(d)
    return datetime_to_excel(date)

# Convert form an excel compatible date number into a datetime.datetime
def excel_to_datetime(d):
    temp = _datetime.datetime(1899, 12, 30)
    delta = _datetime.timedelta(days = d)
    return temp + delta

# Convert form an excel compatible date number into a scripting date value
def excel_to_evsdate(d):
    date = excel_to_datetime(d)
    return datetime_to_evsdate(date)