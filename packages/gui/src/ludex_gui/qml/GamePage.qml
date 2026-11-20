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
    onVisibleChanged: if (visible) backButton.forceActiveFocus()

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
                        primary: true
                        fontSize: 18
                        implicitHeight: 52
                        implicitWidth: 200
                        text: page.installed ? "▶  Play" : "⇩  Install"
                        onClicked: page.installed ? backend.launch(game.gameId) : backend.install(game.gameId)
                    }
                    Btn {
                        implicitHeight: 52
                        text: "Launch options"
                        onClicked: options.openFor(game.gameId)
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
