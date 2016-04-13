
/* Drop Tables */

DROP TABLE [observation];
DROP TABLE [sensor_property];
DROP TABLE [observed_property];
DROP TABLE [sensor];




/* Create Tables */

CREATE TABLE [sensor]
(
	[MAC] text NOT NULL,
	[URN] text NOT NULL,
	[FOI_URN] text NOT NULL,
	[UID] text NOT NULL,
	PRIMARY KEY ([UID])
);


CREATE TABLE [observed_property]
(
	[ID] integer PRIMARY KEY,
	[name] text NOT NULL,
	[URN] text NOT NULL,
	[size] integer NOT NULL,
	[UOM] text
);


CREATE TABLE [observation]
(
	[sensor_ID] integer NOT NULL,
	[property_ID] integer NOT NULL,
	[time_utc] text NOT NULL,
	[value] real NOT NULL,
	PRIMARY KEY ([sensor_ID], [property_ID], [time_utc]),
	FOREIGN KEY ([sensor_ID])
	REFERENCES [sensor] ([ID]),
	FOREIGN KEY ([property_ID])
	REFERENCES [observed_property] ([ID])
);


CREATE TABLE [sensor_property]
(
	[sensor_ID] integer NOT NULL,
	[property_ID] integer NOT NULL,
	[row_order] integer NOT NULL,
	PRIMARY KEY ([sensor_ID], [property_ID]),
	FOREIGN KEY ([sensor_ID])
	REFERENCES [sensor] ([ID]),
	FOREIGN KEY ([property_ID])
	REFERENCES [observed_property] ([ID])
);
