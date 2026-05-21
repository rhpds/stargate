-- Create databases for both StarGate and Launchpad on shared postgres
CREATE USER stargate WITH PASSWORD 'stargate';
CREATE USER launchpad WITH PASSWORD 'launchpad';
CREATE DATABASE stargate OWNER stargate;
CREATE DATABASE launchpad OWNER launchpad;
