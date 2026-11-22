import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Item {
    id: page
    property bool installedOnly: false
    property string store: ""
    property string genre: ""
    readonly property var genreNames: backend.genres.map(g => g.genre)
    readonly property var sortKeys: ["title", "recent", "playtime", "installed"]

    function apply() {
        backend.setFilter(search.text, page.store, page.installedOnly, sortKeys[sortBox.currentIndex], page.genre)
    }
    function playCurrent() {
        var card = grid.currentItem
        if (card) card.installed ? backend.launch(card.gameId) : backend.install(card.gameId)
    }
    function focusGrid() {
        grid.forceActiveFocus()
    }
    function focusSearch() {
        search.forceActiveFocus()
        search.selectAll()
    }

    onInstalledOnlyChanged: apply()
    onStoreChanged: apply()
    onGenreChanged: apply()
    onVisibleChanged: if (visible) {
        apply()
        grid.forceActiveFocus()
    }

    Timer { id: debounce; interval: 160; onTriggered: page.apply() }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: consoleMode ? 32 : 24
        spacing: 14

        RowLayout {
            Layout.fillWidth: true
            spacing: 12
            Txt {
                visible: !consoleMode
                text: page.installedOnly ? "Installed" : "Library"
                font.pixelSize: Theme.title
                font.bold: true
            }
            Txt { text: backend.count + (backend.count === 1 ? " game" : " games"); color: Theme.muted; Layout.alignment: Qt.AlignBottom; Layout.bottomMargin: 4 }
            Item { Layout.fillWidth: true; Layout.minimumWidth: 0 }
            TextField {
                id: search
                Layout.fillWidth: true
                Layout.maximumWidth: 280
                Layout.minimumWidth: 120
                placeholderText: "Search your library   ( / )"
                color: Theme.text
                placeholderTextColor: Theme.muted
                font.family: Theme.family
                font.pixelSize: Theme.body
                selectByMouse: true
                leftPadding: 14
                implicitHeight: 36
                background: Rectangle {
                    radius: height / 2
                    color: Theme.surface2
                    border.width: search.activeFocus ? 2 : 1
                    border.color: search.activeFocus ? Theme.accent : Theme.border
                }
                onTextChanged: debounce.restart()
                Keys.onEscapePressed: { text = ""; grid.forceActiveFocus() }
                Keys.onDownPressed: grid.forceActiveFocus()
                Keys.onReturnPressed: grid.forceActiveFocus()
            }
            Combo {
                id: sortBox
                objectName: "sortBox"
                Layout.preferredWidth: 170
                Layout.minimumWidth: 120
                model: ["Title", "Recently played", "Play time", "Installed first"]
                onActivated: page.apply()
            }
            Btn {
                visible: !consoleMode
                text: backend.refreshing ? "Refreshing…" : "Refresh"
                enabled: !backend.refreshing
                onClicked: { backend.reload(); backend.startRefresh(false) }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 12
            visible: backend.stores.length > 1 || backend.genres.length > 0 || backend.missingDetails > 0
            Flow {
                Layout.fillWidth: true
                spacing: 8
                visible: backend.stores.length > 1
                Chip { text: "All stores"; checked: page.store === ""; onClicked: page.store = "" }
                Repeater {
                    model: backend.stores
                    delegate: Chip { required property string modelData; text: modelData; checked: page.store === modelData; onClicked: page.store = modelData }
                }
            }
            Item { Layout.fillWidth: true; visible: backend.stores.length <= 1 }
            Combo {
                id: genreBox
                objectName: "genreBox"
                visible: backend.genres.length > 0
                Layout.preferredWidth: 220
                model: ["All genres"].concat(backend.genres.map(g => g.genre + " (" + g.games + ")"))
                currentIndex: page.genreNames.indexOf(page.genre) + 1
                onActivated: page.genre = currentIndex > 0 ? page.genreNames[currentIndex - 1] : ""
            }
            Btn {
                visible: backend.missingDetails > 0 || backend.fetchingDetails !== ""
                text: backend.fetchingDetails !== "" ? backend.fetchingDetails + "  (stop)" : "Fetch details (" + backend.missingDetails + ")"
                ToolTip.visible: hovered
                ToolTip.text: "Ask the stores for the genres and descriptions of games that have none. They see the game ids."
                onClicked: backend.fetchingDetails !== "" ? backend.stopFetchingDetails() : backend.fetchAllDetails()
            }
        }

        GridView {
            id: grid
            objectName: "grid"
            activeFocusOnTab: true
            Layout.fillWidth: true
            Layout.fillHeight: true
            readonly property int columns: Math.max(2, Math.floor(width / (consoleMode ? 220 : 190)))
            cellWidth: Math.floor(width / columns)
            cellHeight: Math.round(cellWidth * 1.5) + (consoleMode ? 84 : 62)
            clip: true
            focus: true
            keyNavigationEnabled: true
            highlightFollowsCurrentItem: true
            cacheBuffer: 0  // only cards on screen exist, so only they ask for covers
            model: backend.gameModel
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            delegate: GameCard {
                width: grid.cellWidth
                height: grid.cellHeight
                current: GridView.isCurrentItem && grid.activeFocus
                onOpened: { grid.currentIndex = index; backend.openGame(gameId) }
            }
            Keys.onReturnPressed: if (currentItem) backend.openGame(currentItem.gameId)
            Keys.onEnterPressed: if (currentItem) backend.openGame(currentItem.gameId)

            Txt {
                anchors.centerIn: parent
                visible: backend.count === 0
                horizontalAlignment: Text.AlignHCenter
                color: Theme.muted
                text: page.installedOnly ? "No installed games found." : (search.text !== "" || page.store !== "" ? "No game matches." : "No games here yet.\nAdd a source with 'ludex account add' and run 'ludex import'.")
            }
        }
    }
}
