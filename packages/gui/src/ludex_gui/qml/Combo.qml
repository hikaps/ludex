import QtQuick
import QtQuick.Controls.Basic

ComboBox {
    id: box
    implicitHeight: 36
    font.family: Theme.family
    // Closed, the arrows move focus like on every other control; Return opens the list.
    Keys.onUpPressed: (event) => step(event, false)
    Keys.onDownPressed: (event) => step(event, true)
    // The release of the key that opened the list must not reach ComboBox, which would close it again.
    property bool opening: false
    Keys.onReturnPressed: (event) => openList(event)
    Keys.onEnterPressed: (event) => openList(event)
    Keys.onReleased: (event) => {
        if (opening && (event.key === Qt.Key_Return || event.key === Qt.Key_Enter)) { opening = false; event.accepted = true }
    }
    function openList(event) {
        if (popup.visible) { event.accepted = false; return }
        opening = true
        popup.open()
        event.accepted = true
    }
    function step(event, forward) {
        if (popup.visible) { event.accepted = false; return }
        var next = nextItemInFocusChain(forward)
        if (next && next !== box) next.forceActiveFocus(forward ? Qt.TabFocusReason : Qt.BacktabFocusReason)
        event.accepted = true
    }
    contentItem: Txt { leftPadding: 12; text: box.displayText; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
    background: Rectangle { radius: Theme.radius; color: Theme.surface2; border.width: box.activeFocus ? 2 : 1; border.color: box.activeFocus ? Theme.accent : Theme.border }
    delegate: ItemDelegate {
        required property var modelData
        required property int index
        width: box.width
        contentItem: Txt { text: modelData }
        background: Rectangle { color: highlighted ? Theme.surface3 : Theme.surface2 }
        highlighted: box.highlightedIndex === index
    }
    popup.background: Rectangle { color: Theme.surface2; border.width: 1; border.color: Theme.border; radius: Theme.radius }
}
