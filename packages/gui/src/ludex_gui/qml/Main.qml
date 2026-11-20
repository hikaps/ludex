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
    title: "ludex"
    color: Theme.bg
    font.family: Theme.family

    property string section: "library"
    readonly property bool gameOpen: backend.current.gameId !== undefined

    function go(name) {
        backend.closeGame()
        section = name
    }
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

    Shortcut { sequence: "Ctrl+1"; onActivated: win.go("library") }
    Shortcut { sequence: "Ctrl+2"; onActivated: win.go("installed") }
    Shortcut { sequence: "Ctrl+3"; onActivated: win.go("search") }
    Shortcut { sequence: "Ctrl+4"; onActivated: win.go("jobs") }
    Shortcut { sequence: "Ctrl+5"; onActivated: win.go("settings") }
    Shortcut {
        sequence: "Escape"
        enabled: win.gameOpen
        onActivated: backend.closeGame()
    }
    Shortcut {
        sequence: "/"
        enabled: !(win.activeFocusItem && win.activeFocusItem.hasOwnProperty("cursorPosition"))
        onActivated: {
            if (win.section === "search") {
                search.focusSearch()
            } else if (win.section === "library" || win.section === "installed") {
                win.go(win.section)
                library.focusSearch()
            }
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
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
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

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
                Layout.preferredHeight: 30
                color: Theme.surface
                Txt {
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.margins: 16
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
