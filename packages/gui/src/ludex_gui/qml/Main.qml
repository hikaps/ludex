import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ApplicationWindow {
    id: win
    objectName: "window"
    width: 1280
    height: 800
    minimumWidth: 900
    minimumHeight: 600
    visible: true
    visibility: consoleMode ? Window.FullScreen : Window.Windowed
    title: "ludex"
    color: Theme.bg
    font.family: Theme.family

    property string section: "library"
    readonly property bool gameOpen: backend.current.gameId !== undefined

    function go(name) {
        backend.closeGame()
        section = name
    }
    // Y on the controller and "/" on the keyboard: jump to the search field of the current page.
    function focusSearch() {
        if (inPopup(activeFocusItem)) return
        if (section === "search") {
            search.focusSearch()
        } else if (section === "library" || section === "installed") {
            go(section)
            library.focusSearch()
        }
    }
    // Start on the controller: resume or quit.
    function openMenu() {
        if (!inPopup(activeFocusItem)) menu.open()
    }
    // A on a text field: type with the on-screen keyboard.
    function openKeyboard() {
        var item = activeFocusItem
        if (item && item.hasOwnProperty("cursorPosition")) keyboard.openFor(item)
    }
    function sectionTitle(name) {
        if (name.indexOf("view:") === 0) return backend.views[parseInt(name.split(":")[1])].title
        return {library: "Library", installed: "Installed", search: "Search", jobs: "Jobs", settings: "Settings"}[name]
    }
    readonly property var sections: ["library", "installed", "search", "jobs", "settings"].concat(backend.views.map((v, i) => "view:" + i))

    // The functions below are what the keyboard shortcuts and the controller (gamepad.py) call.
    function cycle(step) {
        if (inPopup(activeFocusItem)) return
        go(sections[(sections.indexOf(section) + step + sections.length) % sections.length])
    }
    function goBack() {
        if (gameOpen) backend.closeGame()
    }
    function playCurrent() {
        if (inPopup(activeFocusItem)) return
        if (gameOpen) {
            gamePage.playOrInstall()
        } else if (section === "library" || section === "installed") {
            library.playCurrent()
        }
    }
    // True while the focus sits inside a dialog or popup, which owns Escape and page keys.
    function inPopup(item) {
        for (var p = item; p; p = p.parent) {
            if (p === Overlay.overlay) return true
        }
        return false
    }
    // Scrolls the nearest Flickable so the focused control stays on screen.
    function ensureVisible(item) {
        if (!item || inPopup(item)) return
        var p = item.parent
        while (p && !(p instanceof Flickable)) p = p.parent
        if (!p || p.contentHeight <= p.height) return
        var y = item.mapToItem(p.contentItem, 0, 0).y
        if (y < p.contentY) {
            p.contentY = Math.max(p.originY, y - 16)
        } else if (y + item.height > p.contentY + p.height) {
            p.contentY = Math.min(p.originY + p.contentHeight - p.height, y + item.height - p.height + 16)
        }
    }
    onActiveFocusItemChanged: ensureVisible(activeFocusItem)
    function pageIndex(name) {
        if (name === "library" || name === "installed") return 0
        if (name === "search") return 1
        if (name === "jobs") return 2
        if (name === "settings") return 3
        return 4 + parseInt(name.split(":")[1])
    }

    onGameOpenChanged: {
        if (gameOpen) {
            gamePage.forceActiveFocus()
        } else {
            library.focusGrid()
        }
    }

    Shortcut { sequence: "F11"; onActivated: backend.switchMode(!consoleMode) }
    Shortcut { sequence: "Ctrl+1"; onActivated: win.go("library") }
    Shortcut { sequence: "Ctrl+2"; onActivated: win.go("installed") }
    Shortcut { sequence: "Ctrl+3"; onActivated: win.go("search") }
    Shortcut { sequence: "Ctrl+4"; onActivated: win.go("jobs") }
    Shortcut { sequence: "Ctrl+5"; onActivated: win.go("settings") }
    Shortcut {
        sequence: "Escape"
        enabled: win.gameOpen && !win.inPopup(win.activeFocusItem)
        onActivated: win.goBack()
    }
    Shortcut { sequence: "Ctrl+PgDown"; onActivated: win.cycle(1) }
    Shortcut { sequence: "Ctrl+PgUp"; onActivated: win.cycle(-1) }
    Shortcut { sequence: "Ctrl+P"; onActivated: win.playCurrent() }
    Shortcut {
        sequence: "/"
        enabled: !(win.activeFocusItem && win.activeFocusItem.hasOwnProperty("cursorPosition"))
        onActivated: win.focusSearch()
    }
    Dialog {
        id: menu
        objectName: "menu"
        modal: true
        anchors.centerIn: Overlay.overlay
        padding: 20
        background: Rectangle { radius: Theme.radius; color: Theme.surface2; border.width: 1; border.color: Theme.border }
        header: Txt { text: "ludex"; font.bold: true; font.pixelSize: 18; padding: 20; bottomPadding: 0 }
        contentItem: Column {
            spacing: 8
            Btn { id: resume; width: 240; text: "Resume"; onClicked: menu.close() }
            Btn {
                objectName: "switchMode"
                width: 240
                text: consoleMode ? "Switch to desktop mode" : "Switch to console mode"
                onClicked: backend.switchMode(!consoleMode)
            }
            Btn { width: 240; text: "Quit ludex"; onClicked: Qt.quit() }
        }
        onOpened: resume.forceActiveFocus(Qt.TabFocusReason)
    }
    OnScreenKeyboard { id: keyboard }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            visible: !consoleMode
            Layout.fillHeight: true
            Layout.preferredWidth: 224
            color: Theme.surface

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 4

                Txt {
                    text: "ludex"
                    font.pixelSize: 26
                    font.bold: true
                    Layout.margins: 8
                    Layout.bottomMargin: 18
                }
                NavItem { objectName: "nav-library"; Layout.fillWidth: true; label: "Library"; glyph: "▤"; current: win.section === "library"; onActivated: win.go("library") }
                NavItem { objectName: "nav-installed"; Layout.fillWidth: true; label: "Installed"; glyph: "▶"; current: win.section === "installed"; onActivated: win.go("installed") }
                NavItem { objectName: "nav-search"; Layout.fillWidth: true; label: "Search"; glyph: "⌕"; current: win.section === "search"; onActivated: win.go("search") }
                NavItem {
                    objectName: "nav-jobs"
                    Layout.fillWidth: true
                    label: "Jobs"
                    glyph: "⇩"
                    badge: backend.runningJobs > 0 ? String(backend.runningJobs) : ""
                    current: win.section === "jobs"
                    onActivated: win.go("jobs")
                }
                NavItem { objectName: "nav-settings"; Layout.fillWidth: true; label: "Settings"; glyph: "⚙"; current: win.section === "settings"; onActivated: win.go("settings") }

                Flickable {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.topMargin: 14
                    contentHeight: plugins.implicitHeight
                    clip: true
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                    Column {
                        id: plugins
                        width: parent.width
                        spacing: 4
                        Txt {
                            visible: backend.views.length > 0
                            text: "PLUGINS"
                            font.pixelSize: 11
                            font.bold: true
                            color: Theme.muted
                            leftPadding: 8
                            bottomPadding: 4
                        }
                        Repeater {
                            model: backend.views
                            delegate: NavItem {
                                required property var modelData
                                required property int index
                                objectName: "nav-view-" + index
                                width: plugins.width
                                label: modelData.title
                                glyph: "◈"
                                current: win.section === "view:" + index
                                onActivated: win.go("view:" + index)
                            }
                        }
                    }
                }
                NavItem { objectName: "nav-console"; Layout.fillWidth: true; label: "Console mode"; glyph: "▣"; onActivated: backend.switchMode(true) }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            Rectangle {
                visible: consoleMode
                objectName: "consoleTabs"
                Layout.fillWidth: true
                Layout.preferredHeight: 64
                color: Theme.surface
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 32
                    anchors.rightMargin: 32
                    spacing: 8
                    Txt { text: "ludex"; font.pixelSize: 26; font.bold: true; Layout.rightMargin: 24 }
                    Repeater {
                        model: win.sections
                        delegate: Item {
                            id: tab
                            required property string modelData
                            readonly property bool here: win.section === modelData
                            objectName: "tab-" + modelData
                            Layout.preferredWidth: tabLabel.implicitWidth + 36
                            Layout.minimumWidth: 72
                            Layout.fillHeight: true
                            activeFocusOnTab: true
                            Keys.onReturnPressed: win.go(modelData)
                            Txt {
                                id: tabLabel
                                anchors.centerIn: parent
                                width: Math.min(implicitWidth, tab.width - 16)
                                elide: Text.ElideRight
                                horizontalAlignment: Text.AlignHCenter
                                text: win.sectionTitle(tab.modelData)
                                font.pixelSize: 18
                                font.bold: tab.here
                                color: tab.here ? Theme.text : Theme.muted
                            }
                            Rectangle {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                height: 4
                                radius: 2
                                color: Theme.accent
                                visible: tab.here
                            }
                            Rectangle {
                                anchors.fill: parent
                                anchors.margins: 6
                                radius: Theme.radius
                                color: "transparent"
                                border.width: tab.activeFocus ? 3 : 0
                                border.color: Theme.text
                            }
                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: win.go(tab.modelData) }
                        }
                    }
                    Item { Layout.fillWidth: true }
                    Chip { visible: backend.runningJobs > 0; text: backend.runningJobs + " running"; checked: true; interactive: false }
                }
            }

            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true

                StackLayout {
                    id: stack
                    anchors.fill: parent
                    enabled: !win.gameOpen
                    currentIndex: win.pageIndex(win.section)

                    LibraryPage { id: library; installedOnly: win.section === "installed" }
                    SearchPage { id: search }
                    JobsPage { }
                    SettingsPage { }
                    Repeater {
                        model: backend.views
                        delegate: PluginViewPage { required property var modelData; page: modelData }
                    }
                }
                GamePage {
                    id: gamePage
                    objectName: "gamePage"
                    anchors.fill: parent
                    visible: win.gameOpen
                    onBack: backend.closeGame()
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: consoleMode ? 44 : 30
                color: Theme.surface
                Txt {
                    id: hints
                    visible: consoleMode
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.right: parent.right
                    anchors.rightMargin: 16
                    objectName: "hints"
                    text: win.gameOpen ? "A Select    B Back    X Play    Start Menu" : "A Open    B Back    X Play    Y Search    LB RB Tabs    Start Menu"
                    font.pixelSize: 15
                    color: Theme.muted
                }
                Txt {
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.left: parent.left
                    anchors.right: consoleMode ? hints.left : parent.right
                    anchors.leftMargin: 16
                    anchors.rightMargin: 16
                    objectName: "status"
                    text: backend.status
                    elide: Text.ElideRight
                    font.pixelSize: Theme.small
                    color: backend.statusError ? Theme.bad : Theme.muted
                }
            }
        }
    }
}
