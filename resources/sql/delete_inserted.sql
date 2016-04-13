DELETE FROM observation
WHERE sensor_ID = '{mac}'
AND time_utc >= '{begin}'
AND time_utc <= '{end}'
;
