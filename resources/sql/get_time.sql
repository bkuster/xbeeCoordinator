SELECT DISTINCT time_utc
FROM observation
WHERE sensor_ID = '{mac}'
AND time_utc >= '{begin}'
AND time_utc <= '{end}'
ORDER BY time_utc ASC, property_ID ASC
;
