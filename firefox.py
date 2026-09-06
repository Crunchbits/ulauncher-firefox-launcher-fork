import sqlite3
import tempfile
import shutil
import configparser
import os
import logging
import urllib.parse

logger = logging.getLogger(__name__)

class FirefoxDatabase:

    def __init__(self):
        # Settings
        self.order = None
        self.limit = None
        self.custom_path = ""
        self.enable_bookmarks = True
        self.enable_history = True
        
        # Database connection state
        self.conn = None

    def update_connection(self):
        """Initializes or re-initializes the database connection using the current preferences."""
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
                
        db_location = self.searchPlaces()
        if not db_location:
            logger.error("Could not locate places.sqlite")
            self.conn = None
            return

        temporary_db_location = tempfile.mktemp()
        shutil.copyfile(db_location, temporary_db_location)

        self.conn = sqlite3.connect(temporary_db_location)
        self.conn.create_function("hostname", 1, self.__getHostname)

    def searchPlaces(self):
        # 1. Check if a custom path is provided
        if self.custom_path and os.path.exists(self.custom_path):
            # Try interpreting the custom path as the root folder containing profiles.ini
            conf_path = os.path.join(self.custom_path, "profiles.ini")
            if os.path.exists(conf_path):
                profile = configparser.RawConfigParser()
                profile.read(conf_path)
                try:
                    prof_path = profile.get("Profile0", "Path")
                    is_relative = profile.get("Profile0", "IsRelative", fallback="1")
                    if is_relative == "1":
                        sql_path = os.path.join(self.custom_path, prof_path, "places.sqlite")
                    else:
                        sql_path = os.path.join(prof_path, "places.sqlite")
                        
                    if os.path.exists(sql_path):
                        return sql_path
                except Exception as e:
                    logger.debug("Failed to parse custom profiles.ini: %s", e)

            # Try interpreting the custom path directly as the profile folder
            direct_sql_path = os.path.join(self.custom_path, "places.sqlite")
            if os.path.exists(direct_sql_path):
                return direct_sql_path

        # 2. Fallback to default Firefox folders
        firefox_path = os.path.join(os.environ["HOME"], ".mozilla/firefox/")
        if not os.path.exists(firefox_path):
            firefox_path = os.path.join(
                os.environ["HOME"], "snap/firefox/common/.mozilla/firefox/"
            )

        conf_path = os.path.join(firefox_path, "profiles.ini")
        logger.debug("Config path %s" % conf_path)
        if not os.path.exists(conf_path):
            return None

        profile = configparser.RawConfigParser()
        profile.read(conf_path)
        try:
            prof_path = profile.get("Profile0", "Path")
        except configparser.NoSectionError:
            return None

        sql_path = os.path.join(firefox_path, prof_path, "places.sqlite")
        logger.debug("Sql path %s" % sql_path)
        if not os.path.exists(sql_path):
            return None

        return sql_path

    def __getHostname(self, string):
        return urllib.parse.urlsplit(string).netloc

    def search(self, query_str):
        if not self.conn:
            return []
            
        # Return early if both features are disabled
        if not self.enable_bookmarks and not self.enable_history:
            return []

        # Base Search query
        terms = query_str.split(" ")
        term_where = []
        for term in terms:
            term_where.append(
                f'((url LIKE "%{term}%") OR (moz_bookmarks.title LIKE "%{term}%") OR (moz_places.title LIKE "%{term}%"))'
            )

        where_clauses = [" AND ".join(term_where)]
        
        # Apply Toggles
        if not self.enable_bookmarks:
            # If bookmarks are disabled, require the item to be a visited history item
            where_clauses.append("moz_places.visit_count > 0")
            
        if not self.enable_history:
            # If history is disabled, require the item to have a bookmark title
            where_clauses.append("moz_bookmarks.title IS NOT NULL AND moz_bookmarks.title <> ''")

        where = " AND ".join(f"({clause})" for clause in where_clauses)

        order_by_dict = {
            "frecency": "frecency", # Fixed to align with the manifest.json
            "frequency": "frequency",
            "visit": "visit_count",
            "recent": "last_visit_date",
        }
        order_by = order_by_dict.get(self.order, "url")

        query = f"""SELECT 
            url, 
            CASE WHEN moz_bookmarks.title IS NOT NULL AND moz_bookmarks.title <> '' 
                THEN moz_bookmarks.title
                ELSE moz_places.title 
            END AS label,
            CASE WHEN moz_bookmarks.title IS NOT NULL AND moz_bookmarks.title <> '' 
                THEN 1
                ELSE 0 
            END AS is_bookmark
            FROM moz_places
                LEFT OUTER JOIN moz_bookmarks ON(moz_bookmarks.fk = moz_places.id)
            WHERE {where}
            ORDER BY is_bookmark DESC, {order_by} DESC
            LIMIT {self.limit};"""

        rows = []
        try:
            cursor = self.conn.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()
        except Exception as e:
            logger.error("Error in query (%s) execution: %s" % (query, e))
        return rows

    def close(self):
        if self.conn:
            self.conn.close()
