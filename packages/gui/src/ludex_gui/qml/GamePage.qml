import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// The page of one game: hero banner, cover, a big Play or Install button, details from the stores.
Item {
    id: page
    readonly property var game: backend.current
    readonly property bool installed: game.installed === true
    readonly property bool running: (game.running || "") !== ""
    signal back()
    focus: visible
    function focusDefault() {
        if (!page.visible) return
        (consoleMode ? playButton : backButton).forceActiveFocus(Qt.TabFocusReason)
    }
    onVisibleChanged: if (visible) Qt.callLater(focusDefault)
    readonly property var stores: game.playStores || []
    // The store a click uses: the one picked next to the button, else the first (an installed copy comes first).
    readonly property string chosenStore: stores.length > 1 && storeBox.currentIndex >= 0 ? stores[storeBox.currentIndex].store : ""
    function playOrInstall() {
        if (installed) backend.launchFrom(game.gameId, chosenStore)
        else backend.installFrom(game.gameId, chosenStore)
    }

    Rectangle { anchors.fill: parent; color: Theme.bg }
    Image {
        anchors.fill: parent
        source: game.coverUrl || ""
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        sourceSize.width: 900
        opacity: 0.32
        verticalAlignment: Image.AlignTop
    }
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#880e1014" }
            GradientStop { position: 0.55; color: "#f00e1014" }
            GradientStop { position: 1.0; color: Theme.bg }
        }
    }

    LaunchOptions { id: options }
    MatchDialog { id: matcher }

    Btn { id: backButton; text: "‹  Back"; x: 24; y: 20; onClicked: page.back() }

    Flickable {
        anchors.fill: parent
        anchors.topMargin: 72
        contentHeight: content.implicitHeight + 48
        clip: true
        ScrollBar.vertical: ScrollBar {}

        RowLayout {
            id: content
            x: 32
            width: parent.width - 64
            spacing: 32

            CoverArt {
                Layout.preferredWidth: 250
                Layout.preferredHeight: 375
                Layout.alignment: Qt.AlignTop
                source: game.coverUrl || ""
                title: game.title || ""
                seed: game.gameId || 0
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignTop
                spacing: 14

                Txt { Layout.fillWidth: true; text: game.title || ""; font.pixelSize: 38; font.bold: true; wrapMode: Text.Wrap }

                Flow {
                    Layout.fillWidth: true
                    spacing: 8
                    Repeater {
                        model: (game.stores || "").length ? String(game.stores).split(", ") : []
                        delegate: Chip { required property string modelData; text: modelData; interactive: false }
                    }
                    Chip { visible: page.installed; text: "Installed"; checked: true; interactive: false }
                    Chip { visible: page.running; text: game.running || ""; checked: true; interactive: false }
                }

                Txt {
                    text: (game.played || "never") === "never" ? "Not played yet" : "Played " + game.played
                    color: Theme.muted
                }

                RowLayout {
                    spacing: 12
                    Btn {
                        id: playButton
                        readonly property string activity: backend.activity[String(game.gameId)] || ""
                        primary: true
                        fontSize: 18
                        implicitHeight: 52
                        implicitWidth: 200
                        text: activity !== "" ? activity + "…" : page.installed ? "▶  Play" : "⇩  Install"
                        enabled: activity === ""
                        onClicked: page.playOrInstall()
                    }
                    Btn {
                        objectName: "cancelStart"
                        visible: playButton.activity === "Starting"
                        implicitHeight: 52
                        text: "Cancel"
                        onClicked: backend.cancelStart(game.gameId)
                    }
                    Combo {
                        id: storeBox
                        objectName: "storeBox"
                        visible: page.stores.length > 1
                        implicitHeight: 52
                        Layout.preferredWidth: 190
                        model: page.stores.map(s => s.store + (s.installed ? " (installed)" : ""))
                        // Back to the first (an installed copy) whenever another game is shown.
                        Connections { target: page; function onGameChanged() { storeBox.currentIndex = 0 } }
                    }
                    Btn {
                        implicitHeight: 52
                        text: "Launch options"
                        onClicked: options.openFor(game.gameId)
                    }
                    Btn {
                        visible: backend.canMatch
                        implicitHeight: 52
                        text: "Match…"
                        onClicked: matcher.openFor(game.gameId, game.title)
                    }
                    Btn {
                        id: moreButton
                        objectName: "moreActions"
                        visible: (game.actions || []).length > 0
                        implicitHeight: 52
                        text: "More  ▾"
                        onClicked: moreMenu.open()
                        Popup {
                            id: moreMenu
                            objectName: "moreMenu"
                            y: moreButton.height + 4
                            padding: 6
                            closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
                            onOpened: if (moreItems.count > 0) moreItems.itemAt(0).forceActiveFocus(Qt.TabFocusReason)
                            background: Rectangle { radius: Theme.radius; color: Theme.surface2; border.width: 1; border.color: Theme.border }
                            contentItem: Column {
                                spacing: 4
                                Repeater {
                                    id: moreItems
                                    model: game.actions || []
                                    delegate: Btn {
                                        required property var modelData
                                        width: 280
                                        text: modelData.label
                                        onClicked: { moreMenu.close(); backend.runAction(game.gameId, modelData.plugin, modelData.id, modelData.store) }
                                    }
                                }
                            }
                        }
                    }
                    Btn {
                        visible: page.running
                        implicitHeight: 52
                        text: "Stop"
                        onClicked: backend.stopGame(game.gameId)
                    }
                }

                Txt {
                    Layout.fillWidth: true
                    Layout.topMargin: 8
                    visible: (game.description || "") !== ""
                    text: game.description || ""
                    wrapMode: Text.Wrap
                    lineHeight: 1.25
                }
                Repeater {
                    model: [
                        { label: "Genres", value: game.genres || "" },
                        { label: "Developers", value: game.developers || "" },
                        { label: "Released", value: game.released || "" },
                        { label: "Details", value: game.matched ? "matched to " + game.matched : "" }
                    ]
                    delegate: RowLayout {
                        required property var modelData
                        visible: modelData.value !== ""
                        Layout.fillWidth: true
                        spacing: 12
                        Txt { text: modelData.label; color: Theme.muted; Layout.preferredWidth: 100 }
                        Txt { text: modelData.value; Layout.fillWidth: true; wrapMode: Text.Wrap }
                    }
                }
                Btn {
                    objectName: "matchLink"
                    visible: (game.matchedUrl || "") !== ""
                    text: "Open " + (game.matched || "") + "  \u2197"
                    onClicked: Qt.openUrlExternally(game.matchedUrl)
                }
                Txt {
                    visible: (game.description || "") === "" && (game.genres || "") === ""
                    color: Theme.muted
                    text: "No details yet. Turn on “Fetch details” in Settings to ask the stores."
                }

                Txt { text: "Copies"; color: Theme.muted; Layout.topMargin: 8 }
                Repeater {
                    model: game.ownership || []
                    delegate: Txt {
                        required property var modelData
                        text: modelData.store + ":" + modelData.storeId + "   " + modelData.account + (modelData.removed ? "   removed" : "")
                        color: modelData.removed ? Theme.muted : Theme.text
                        font.pixelSize: Theme.small
                    }
                }
            }
        }
    }
}
