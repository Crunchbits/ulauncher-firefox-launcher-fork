from ulauncher.api.client.Extension import Extension
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.shared.event import KeywordQueryEvent
from ulauncher.api.shared.event import SystemExitEvent
from ulauncher.api.shared.event import PreferencesUpdateEvent
from ulauncher.api.shared.event import PreferencesEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.action.SetUserQueryAction import SetUserQueryAction
from ulauncher.api.shared.action.OpenUrlAction import OpenUrlAction
from ulauncher.api.shared.action.DoNothingAction import DoNothingAction
from firefox import FirefoxDatabase

import re
import urllib.parse


class FirefoxExtension(Extension):
    def __init__(self):
        super(FirefoxExtension, self).__init__()
        self.database = FirefoxDatabase()
        
        self.subscribe(KeywordQueryEvent, KeywordQueryEventListener())
        self.subscribe(SystemExitEvent, SystemExitEventListener())
        self.subscribe(PreferencesEvent, PreferencesEventListener())
        self.subscribe(PreferencesUpdateEvent, PreferencesUpdateEventListener())


class PreferencesEventListener(EventListener):
    def on_event(self, event: PreferencesEvent, extension: FirefoxExtension):
        extension.database.order = event.preferences["order"]
        try:
            extension.database.limit = int(event.preferences["limit"])
        except ValueError:
            extension.database.limit = 10
            
        extension.database.custom_path = event.preferences.get("custom_path", "")
        extension.database.enable_bookmarks = (event.preferences.get("enable_bookmarks", "True") == "True")
        extension.database.enable_history = (event.preferences.get("enable_history", "True") == "True")
        
        extension.database.update_connection()


class PreferencesUpdateEventListener(EventListener):
    def on_event(self, event: PreferencesUpdateEvent, extension: FirefoxExtension):
        if event.id == "order":
            extension.database.order = event.new_value
        elif event.id == "limit":
            try:
                extension.database.limit = int(event.new_value)
            except ValueError:
                pass
        elif event.id == "custom_path":
            extension.database.custom_path = event.new_value
            extension.database.update_connection()
        elif event.id == "enable_bookmarks":
            extension.database.enable_bookmarks = (event.new_value == "True")
        elif event.id == "enable_history":
            extension.database.enable_history = (event.new_value == "True")


class SystemExitEventListener(EventListener):
    def on_event(self, _: SystemExitEvent, extension: FirefoxExtension):
        extension.database.close()


class KeywordQueryEventListener(EventListener):
    def _parse_url(self, query, default_protocol="https"):
        m = re.match(
            r"^(?:([a-z-A-Z]+)://)?([a-zA-Z0-9/-_]+\.[a-zA-Z0-9/-_\.]+)(?:\?(.*))?$",
            query,
        )
        url = ""
        if m:
            protocol = default_protocol
            if m.group(1):
                protocol = m.group(1)
            base = m.group(2)
            params = m.group(3)
            encoded = f"?{urllib.parse.quote(params)}" if params else ""
            url = f"{protocol}://{base}{encoded}"
        return url

    def on_event(self, event: KeywordQueryEvent, extension: FirefoxExtension):
        query = event.get_argument() if event.get_argument() else ""
        items = []

        url = self._parse_url(query)
        search_engine_url = extension.preferences.get("search_engine", "https://www.google.com/search?q=%s")

        if query:
            if url:
                desc = f"Open URL: {url}"
                action = OpenUrlAction(url)
            else:
                # If not a valid URL, treat as a search query
                encoded_query = urllib.parse.quote_plus(query)
                if "%s" in search_engine_url:
                    search_url = search_engine_url.replace("%s", encoded_query)
                else:
                    search_url = f"{search_engine_url}{encoded_query}"
                
                desc = f"Search for '{query}'"
                action = OpenUrlAction(search_url)
        else:
            desc = "Type a URL or search query and press Enter..."
            action = DoNothingAction()

        items.append(
            ExtensionResultItem(
                icon="images/icon.png",
                name="Search Query",
                description=desc,
                on_enter=action,
            )
        )

        # Search Firefox bookmarks and history
        results = extension.database.search(query)

        for link in results:
            url_link = link[0]
            title = link[1] if link[1] else url_link

            if url_link != query:
                items.append(
                    ExtensionResultItem(
                        icon="images/icon.png",
                        name=title,
                        description=url_link,
                        on_enter=OpenUrlAction(url_link),
                        on_alt_enter=SetUserQueryAction(
                            f'{extension.preferences["kw"]} {url_link}'
                        ),
                    )
                )

        return RenderResultListAction(items)

if __name__ == "__main__":
    FirefoxExtension().run()
