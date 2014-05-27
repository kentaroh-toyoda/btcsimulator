View = require 'views/base/view'
template = require 'templates/simulation/network'
Summary = require 'models/summary'

module.exports = class NetworkView extends View
  template: template
  id: 'network'
  className: 'container'
  summaryBindings:
    "#total-blocks": "blocks"
    "#miners": "miners"
    "#days": "days"
    "#links":
      observe: 'links'
      onGet: (value) -> if value? then value / 2 else ""
    "#events": "events"
  minerBindings:
    "#miner-id": "id"
    "#blocks-mined": "blocks_mined"
    "#hash-rate":
      observe: "hashrate"
      onGet: (value) -> if value? then parseFloat(value).toFixed(2) else ""
    "#miner-links":
      observe: "links"
      onGet: (value) -> if value? then value.length else 0


  initialize: ->
    super
    @summary = new Summary.Model()
    @summary.fetch reset: true
    console.log @summary
    @listenTo @collection, 'reset', @createNetwork
    @listenTo @, 'addedToDOM', @fetchNetwork

  fetchNetwork: ->
    @$('#network-container').height @$('.row').height()
    @collection.fetch reset: true

  render: ->
    super
    @stickit @summary, @summaryBindings

  createNetwork: () ->
    @miner = @collection.at(0)
    @stickit @miner, @minerBindings
    console.log(@miner.toJSON())
    data = @collection.getNetwork()
    width = @$('#network-chart').width() - 40
    height = @$('#network-chart').height() - 40
    color = d3.scale.category20()
    force = d3.layout.force()
    .charge(-120)
    .linkDistance(180)
    .size([width, height])
    .gravity(0.5)

    svg = d3.select('#network-chart').append('svg')
    .attr('width', width)
    .attr('height', height)

    g = svg.selectAll('g')
    .data([data])
    .enter().append("g")

    force.nodes(data.nodes)
    .links(data.links)
    .start()

    link = g.selectAll('.link')
    .data(data.links)
    .enter().append("line")
    .attr("class", "link")
    .style("stroke-width", (d) -> 0.5)
    .style("stroke", '#000')

    node = g.selectAll(".node")
    .data(data.nodes)
    .enter().append("circle")
    .attr("class", "node")
    .attr("r", (d) -> 5 + 20*d.hashrate)
    .style("fill", (d) -> color(d.id))
    .style("stroke", "#fff")
    .style("stroke-width", "1.5px")
    .call(force.drag)

    node.append("title")
    .text((d) -> "Miner #{d.id}")

    force.on("tick", () ->
      link.attr("x1", (d) -> d.source.x)
      .attr("y1", (d) -> d.source.y)
      .attr("x2", (d) -> d.target.x)
      .attr("y2", (d) -> d.target.y)

      node.attr("cx", (d) -> d.x)
      node.attr("cy", (d) -> d.y)
    )

  dispose: ->
    super
    @unstickit()
